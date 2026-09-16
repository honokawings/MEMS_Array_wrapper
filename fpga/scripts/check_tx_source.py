"""Fail-closed engineering audit of PDS RGMII source timing, using original evidence.

The text RTR's ``All Constraints Met`` omits the MaxSkew tables. This module
checks those tables, independently recomputes physical same-edge differences,
and keeps duty-cycle qualification separate. No report is edited. Standard
library only; no PDS installation is required to audit an existing report.

PASS is restricted to engineering_board_bringup and never means unconditional
board qualification. The shaped-clock path is reconstructed from actual PDS
netlists/SDF; nominal model duty and an additional jitter sensitivity analysis
are reported separately. An unshaped 45..55 percent board oscillator is not
silently replaced with the ideal 50 percent waveform from create_clock.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

PORTS = frozenset({"PHY0_TXC", "PHY0_TXCTRL", *(f"PHY0_TXD[{i}]" for i in range(4))})
EPS = 0.0011  # XML reports to 1 ps; permit only its rounding error.


class AuditError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise AuditError(message)


def fields(row):
    need(row is not None, "Missing XML row")
    return [n.text or "" for n in row.findall("data")]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def number(text):
    value = float(text)
    need(value == value and abs(value) < 1e6, f"Invalid timing number: {text}")
    return value


def arrival(row, source_port):
    table = row.find("general_container/table_container/table[@id='arrival']")
    need(table is not None, "Missing full physical arrival table")
    match = re.fullmatch(r"Data arrival time is (-?[\d.]+)", table.get("title", ""))
    need(match is not None, "Unrecognized arrival title")
    rows = [fields(r) for r in table.findall("row")]
    need(all(len(r) == 6 for r in rows), "Unexpected arrival columns")
    need(rows[0][5] == source_port + " (port)", "Arrival no longer starts at the physical clock port")
    need(number(rows[0][3]) == 0, "Nonzero source phase in same-edge comparison")
    need(rows[0][4] in ("r", "f"), "Missing physical source transition")
    need(any(r[1] == "tco" for r in rows), "Missing ODDR clock-to-output arc")
    need(any(r[0].endswith("/OCLK") for r in rows), "Missing ODDR clock pin")
    require = row.find("general_container/table_container/table[@id='require']")
    need(require is not None, "Missing requirement table")
    uncertainty = []
    for item in require.findall("row"):
        f = fields(item)
        if f[0] == "clock uncertainty":
            uncertainty.append(number(f[2]))
        elif f[0] in ("Output external delay", "clock pessimism"):
            need(number(f[2]) == 0, "Nonzero external delay or physical capture path contaminates skew")
        else:
            raise AuditError(f"Unexpected capture-path term: {f[0]}")
    need(len(uncertainty) == 1, "Expected exactly one reported uncertainty term")
    return {"arrival_ns": number(match[1]), "source_edge": rows[0][4],
            "output_edge": rows[-1][4], "uncertainty_ns": uncertainty[0], "rows": rows}


def check_constraints(path, reference_clock, launch_clock):
    lines = [x.split("#", 1)[0].strip() for x in Path(path).read_text(encoding="utf-8").splitlines()]
    lines = [x for x in lines if x]
    ref = [x for x in lines if re.search(r"^create_clock\s+-name\s+" + re.escape(reference_clock) + r"\b", x)]
    need(len(ref) == 1 and "get_ports" not in ref[0] and "get_pins" not in ref[0], "TX reference must be one virtual clock")
    need(re.search(r"-period\s+8(?:\.0*)?(?:\s|$)", ref[0]), "TX reference must have 8 ns period")
    waveform = re.search(r"-waveform\s+\{([^}]+)\}", ref[0])
    need(waveform is None or [float(v) for v in waveform[1].split()] == [0, 4], "TX reference must have zero phase")
    need(not any(x.startswith("create_generated_clock") and "PHY0_TXC" in x for x in lines), "TXC must be a data endpoint")
    outputs = [x for x in lines if x.startswith("set_output_delay") and "PHY0_TX" in x]
    need(len(outputs) == 4, "Expected four zero-reference TX output delays")
    signatures = set()
    for line in outputs:
        need(all(p in line for p in ("PHY0_TXC", "PHY0_TXD[*]", "PHY0_TXCTRL")), "Output delay misses a TX endpoint")
        need(re.search(r"-clock\s+" + re.escape(reference_clock) + r"\b", line), "Mixed TX capture references")
        m = re.search(r"-(max|min)\s+(-?[\d.]+)", line)
        need(m is not None and float(m[2]) == 0, "TX output delay must be zero")
        signatures.add((m[1], "-clock_fall" in line))
    need(signatures == {(m, e) for m in ("max", "min") for e in (False, True)}, "Incomplete TX DDR references")
    skews = [x for x in lines if x.startswith("set_max_skew") and "PHY0_TX" in x]
    need(len(skews) == 2, "Expected two TX source-edge skew constraints")
    edges = set()
    for line in skews:
        need(all(p in line for p in ("PHY0_TXC", "PHY0_TXD[*]", "PHY0_TXCTRL", launch_clock)), "Skew constraint misses a source/endpoint")
        need(re.search(r"\s0\.400\s*$", line), "Native skew bound must be 0.400 ns")
        edges.add("rise" if "-rise_from" in line else "fall" if "-fall_from" in line else "invalid")
    need(edges == {"rise", "fall"}, "Skew must distinguish both source edges")
    maxima = [x for x in lines if x.startswith("set_max_delay") and "PHY0_TX" in x]
    need(len(maxima) == 1 and re.search(r"^set_max_delay\s+2\.500\s", maxima[0]), "Missing 2.500 ns TX internal path bound")
    need("-datapath_only" in maxima[0] and launch_clock in maxima[0], "Incorrect TX max-delay scope")
    need(all(p in maxima[0] for p in ("PHY0_TXC", "PHY0_TXD[*]", "PHY0_TXCTRL")), "Max delay misses a TX endpoint")
    need(not any(x.startswith("set_false_path") and "PHY0_TX" in x for x in lines), "TX timing cannot be false-pathed")


def parse_cells(netlist):
    """Read only PDS primitive instances; reject unknown clock-path structures."""
    text = Path(netlist).read_text(encoding="utf-8")
    instances = {}
    pattern = r"\b(V_\w+)\s+(?:/\*.*?\*/\s*)?(?:#\((.*?)\)\s*)?(\\\S+|\w+)\s*\((.*?)\);"
    for m in re.finditer(pattern, text, re.S):
        kind, params, name, body = m.groups()
        norm = lambda value: re.sub(r"\s+", "", value).lstrip("\\")
        ports = {k: norm(v) for k, v in re.findall(r"\.(\w+)\s*\(([^()]*)\)", body)}
        values = {k: v.strip() for k, v in re.findall(r"\.(\w+)\s*\(([^()]*)\)", params or "")}
        need(name.lstrip("\\") not in instances, "Duplicate primitive instance")
        instances[name.lstrip("\\")] = {"kind": kind, "ports": ports, "params": values}
    need(instances, "No PDS primitive instances in simulation netlist")
    return instances


def parse_sdf(path):
    """Small S-expression reader for PDS absolute, scalar corner SDF files."""
    text = Path(path).read_text(encoding="utf-8")
    stack, roots = [], []
    for token in re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', re.sub(r"//[^\n]*", "", text)):
        if token == "(":
            node = []
            (stack[-1] if stack else roots).append(node)
            stack.append(node)
        elif token == ")":
            need(stack, "Malformed SDF closing parenthesis")
            stack.pop()
        else:
            need(stack, "Unexpected SDF atom")
            stack[-1].append(token.strip('"').replace("\\/", "/"))
    need(not stack and len(roots) == 1 and roots[0][0] == "DELAYFILE", "Malformed SDF")
    top = roots[0]
    unit = [n for n in top if isinstance(n, list) and n[0] == "TIMESCALE"]
    need(len(unit) == 1 and unit[0][1:] == ["1", "ps"], "Expected 1 ps SDF timescale")
    cells = {}
    for c in top:
        if not isinstance(c, list) or not c or c[0] != "CELL":
            continue
        name = next(n[1] for n in c if isinstance(n, list) and n[0] == "INSTANCE")
        kind = next(n[1] for n in c if isinstance(n, list) and n[0] == "CELLTYPE")
        delay = next((n for n in c if isinstance(n, list) and n[0] == "DELAY"), None)
        if delay is None:
            continue
        need(len(delay) == 2 and delay[1][0] == "ABSOLUTE", "Only absolute corner SDF is supported")
        entries = {}
        for item in delay[1][1:]:
            need(item[0] in ("PORT", "IOPATH"), "Unknown SDF delay construct")
            count = 1 if item[0] == "PORT" else 2
            need(all(isinstance(x, str) for x in item[1:count+1]), "Conditional SDF arcs need separate review")
            values = item[count+1:]
            need(len(values) == 2 and all(isinstance(v, list) and len(v) == 1 for v in values), "Missing rise/fall SDF values")
            need(all(":" not in v[0] for v in values), "Expected one explicit PVT corner, not unselected triples")
            pair = tuple(number(v[0]) / 1000 for v in values)
            key = tuple(item[:count+1])
            need(key not in entries or entries[key] == pair, "Unequal duplicate SDF arcs")
            entries[key] = pair
        cells[name] = {"kind": kind, "delays": entries}
    return cells


def shaped_clock_duty(sdf_paths, netlist_paths):
    """Reconstruct feasible TXC edges from consecutive 250 MHz rising edges.

    The same input polarity traverses the common PLL-to-divider route. After
    the divide-by-two flop, physical rise/fall arcs are followed separately.
    This uses actual corner propagation, not an STA-required-time equation.
    180 ps is conservatively assigned to EACH edge because DS04001 does not
    define whether TOUTJIT is period, phase or peak-to-peak jitter.
    """
    cases = []
    baseline_cells = None
    for corner in ("slow", "fast"):
        cells, delays = parse_cells(netlist_paths[corner]), parse_sdf(sdf_paths[corner])
        header = Path(sdf_paths[corner]).read_text(encoding="utf-8")[:200]
        need(f"{corner.capitalize()} Corner" in header, "Missing/mismatched SDF process-corner label")
        need(baseline_cells is None or baseline_cells == cells, "Slow and fast netlists describe different routed circuits")
        baseline_cells = cells
        def driver(net, allowed):
            found = [(name, c, output) for name, c in cells.items() for output in allowed.get(c["kind"], ())
                     if c["ports"].get(output) == net]
            need(len(found) == 1, f"Unknown or ambiguous driver for {net}")
            return found[0]
        out_name, out, _ = driver("PHY0_TXC", {"V_OBUFT": ("O",)})
        need(out["ports"].get("T") == "1'b0", "TXC pad cannot be tristated")
        oddr_name, oddr, _ = driver(out["ports"]["I"], {"V_OSERDES_E2": ("DO",)})
        need(oddr["params"].get("OSERDES_MODE") == '"DDR2TO1_SAME_EDGE"', "TXC serializer mode changed")
        di = oddr["ports"].get("DI", "").strip("{}").split(",")
        need(len(di) == 8 and di[-1] == "1'b1", "TXC D0 must be constant one")
        zeros = {"1'b0"}
        for cell in cells.values():
            if cell["kind"] == "V_LUT6CARRY" and re.fullmatch(r"64'b0{64}", cell["params"].get("INIT", "")):
                zeros.update(cell["ports"].get(p, "") for p in ("Z", "Z5"))
        need(di[-2] in zeros, "TXC D1 is not proven constant zero")
        need(oddr["ports"].get("OCE") == "1'b1", "TXC clock is gated by OCE")
        buf_name, buf, _ = driver(oddr["ports"]["OCLK"], {"V_USCM": ("CLKOUT",)})
        need(buf["params"].get("USCM_MODE") == '"BUF_A"', "Unexpected clock mux mode")
        div_name, div, _ = driver(buf["ports"]["CLK0"], {"V_IOCLKDIV_E2": ("CLKDIVOUT",)})
        need(div["params"].get("DIV_FACTOR") == '"2"' and div["ports"].get("CE") == "1'b1", "TXC requires ungated single-edge divide-by-two")
        pll_name, pll, output = driver(div["ports"]["CLKIN"], {"V_GPLL": ("CLKOUT0",)})
        # PDS's generated netlist carries the true PLL divider parameters.
        p = pll["params"]
        expected = {"STATIC_RATIOI": "1", "STATIC_RATIOM": "4", "STATIC_RATIOF": "2", "STATIC_RATIO0": "4"}
        for key, value in expected.items():
            need(p.get(key) == value, f"Unverified 125-to-250 MHz PLL parameter {key}={p.get(key)}")
        need(p.get("INTERNAL_FB") == '"CLKOUTF"', "Unexpected PLL feedback")
        need(p.get("SSC_MODE", '"DISABLE"') == '"DISABLE"', "Spread spectrum invalidates the duty budget")
        def arc(name, key):
            need(name in delays and delays[name]["kind"] == cells[name]["kind"], f"SDF/netlist cell mismatch: {name}")
            need(key in delays[name]["delays"], f"Missing SDF arc {name} {key}")
            return delays[name]["delays"][key]
        common = arc(div_name, ("PORT", "CLKIN"))[0]
        pairs = [arc(div_name, ("IOPATH", "CLKIN", "CLKDIVOUT")),
                 arc(buf_name, ("PORT", "CLK0")), arc(buf_name, ("IOPATH", "CLK0", "CLKOUT")),
                 arc(oddr_name, ("PORT", "OCLK")), arc(oddr_name, ("IOPATH", "OCLK", "DO")),
                 arc(out_name, ("PORT", "I")), arc(out_name, ("IOPATH", "I", "O"))]
        rise, fall = [common + sum(pair[e] for pair in pairs) for e in (0, 1)]
        dcd = fall - rise
        jitter = 0.360
        low, high = 4 + dcd - jitter, 4 + dcd + jitter
        # Retain the shared e0/e1/e2 in numerator AND denominator. Combining
        # independent H extrema with independent T extrema would double-count
        # the very same edge error. Linear-fractional extrema on this box are
        # at its vertices, which are inexpensive to enumerate exactly.
        scenarios = []
        for e0, e1, e2 in itertools.product((-0.180, 0.180), repeat=3):
            h = 4 + dcd + e1 - e0
            period = 8 + e2 - e0
            scenarios.append({"edge_errors_ns": [e0, e1, e2], "high_ns": round(h, 3),
                              "period_ns": round(period, 3), "duty_percent": round(100*h/period, 6)})
        duty_min = min(scenarios, key=lambda x: x["duty_percent"])
        duty_max = max(scenarios, key=lambda x: x["duty_percent"])
        cases.append({"corner": corner, "pll_cell": pll_name, "divider_cell": div_name,
            "clock_buffer_cell": buf_name, "txc_oddr_cell": oddr_name, "txc_pad_cell": out_name,
            "pll_posedge_to_txc_rise_ns": round(rise, 3), "next_pll_posedge_to_txc_fall_ns": round(fall, 3),
            "fall_minus_rise_ns": round(dcd, 3), "high_width_envelope_ns": [round(low, 3), round(high, 3)],
            "low_width_envelope_ns": [round(8-high, 3), round(8-low, 3)],
            "minimum_duty_scenario": duty_min, "maximum_duty_scenario": duty_max,
            "all_correlated_edge_scenarios": scenarios,
            "pass": duty_min["duty_percent"] >= 45 and duty_max["duty_percent"] <= 55})
    sensitivity = {"status": "PASS" if all(c["pass"] for c in cases) else "FAIL", "cases": cases,
        "edge_jitter_budget_ns": 0.360,
        "assumption": "Sensitivity only: interpret undefined TOUTJIT 180 ps as +/-180 ps per edge",
        "vendor_metric_is_defined": False,
        "method": "Enumerate three shared edge errors; do not independently worsen numerator and denominator"}
    nominal = []
    for case in cases:
        dcd = case["fall_minus_rise_ns"]
        nominal.append({"corner": case["corner"], "fall_minus_rise_ns": dcd,
            "high_ns": round(4+dcd, 3), "low_ns": round(4-dcd, 3),
            "duty_percent": round(100*(4+dcd)/8, 6),
            "required_edgepair_jitter_max_ns": round(0.4-abs(dcd), 3),
            "pass": abs(dcd) <= 0.4,
            **{key:case[key] for key in ("pll_cell", "divider_cell", "clock_buffer_cell", "txc_oddr_cell", "txc_pad_cell",
                                       "pll_posedge_to_txc_rise_ns", "next_pll_posedge_to_txc_fall_ns")}})
    nominal_status = "PASS" if all(c["pass"] for c in nominal) else "FAIL"
    return {"status": nominal_status, "nominal_model_status": nominal_status, "cases": nominal,
            "qualification_status": "UNCONFIRMED", "sensitivity_status": sensitivity["status"],
            "conservative_jitter_sensitivity": sensitivity,
            "required_edgepair_jitter_max_ns": min(c["required_edgepair_jitter_max_ns"] for c in nominal),
            "period_ns": 8, "required_output_duty_percent": [45, 55],
            "method": "Actual reachable TXC transitions after a 250 MHz positive-edge divide-by-two",
            "qualification_boundary": "Model-based engineering bring-up only; vendor jitter metric, physical slew and board TXC duty require qualification",
            "source": "https://www.pangomicro.com/en/uploads/13964872_1729131653.pdf#page=32"}


def audit_tx_source(report_db, constraints, *, reference_clock="tx_pad_ref", launch_clock="eth125",
                    source_port="sys_clk_125_p", input_duty_min_percent=45.0,
                    input_duty_max_percent=55.0, edge_jitter_budget_ns=0.1,
                    sdf_paths=None, netlist_paths=None):
    """Return model-based engineering evidence, not an unconditional board qualification.

    Numeric duty arguments express an external hardware contract, not a way
    to derive the oscillator specification from a create_clock statement.
    The release caller should use the documented defaults unless a separately
    reviewed board source specification changes.
    """
    report_db, constraints = Path(report_db), Path(constraints)
    result = {"schema_version": 1, "status": "FAIL", "errors": [], "cases": [],
              "scope": "engineering_board_bringup", "unconditional_board_qualification": False,
              "duty": {"status": "FAIL"}, "physical_limit_ns": 0.3,
              "native_limit_ns": 0.4, "pcb_relative_skew_budget_ns": 0.2,
              "inputs": {"report_db": str(report_db.resolve()), "constraints": str(constraints.resolve()),
                         "report_db_sha256": sha256(report_db), "constraints_sha256": sha256(constraints),
                         "helper_sha256": sha256(__file__)}}
    try:
        check_constraints(constraints, reference_clock, launch_clock)
        need((sdf_paths is None) == (netlist_paths is None), "SDF and simulation netlists must be provided together")
        if sdf_paths is not None:
            need(set(sdf_paths) == set(netlist_paths) == {"slow", "fast"}, "Both PVT corners are required")
            for corner in ("slow", "fast"):
                for suffix, paths in (("sdf", sdf_paths), ("netlist", netlist_paths)):
                    key = f"{corner}_{suffix}"
                    result["inputs"][key] = str(Path(paths[corner]).resolve())
                    result["inputs"][key + "_sha256"] = sha256(paths[corner])
        need(0 < input_duty_min_percent <= input_duty_max_percent < 100, "Invalid source duty range")
        need(edge_jitter_budget_ns >= 0, "Negative cross-edge jitter budget")
        root = ET.parse(report_db).getroot()
        txc_envelopes = {}
        coverage = set()
        for corner in ("slow", "fast"):
            tables = [t for t in root.iter("table") if t.get("id") == f"report_timing_{corner}_path_max_skew"]
            need(len(tables) == 1, f"Missing/duplicate {corner} MaxSkew table")
            for constraint in tables[0].findall("row"):
                c = fields(constraint)
                need(len(c) == 14, "Unexpected MaxSkew schema")
                case = {"corner": corner, "constraint": c[0], "native_actual_ns": number(c[11]),
                        "native_slack_ns": number(c[1]), "paths": []}
                need(abs(number(c[10]) - 0.4) < EPS, "Unexpected native MaxSkew limit")
                need(case["native_slack_ns"] >= 0 and case["native_actual_ns"] <= 0.4, "Native MaxSkew violation")
                edges = set()
                groups = set()
                for group in constraint.findall("row"):
                    group_name = fields(group)[0]
                    need(group_name in ("skew for max path", "skew for min path"), "Unknown MaxSkew group")
                    need(group_name not in groups, "Duplicate MaxSkew group")
                    groups.add(group_name)
                    is_max = group_name == "skew for max path"
                    seen = set()
                    for row in group.findall("row"):
                        f = fields(row)
                        refs = row.findall("row")
                        need(len(refs) == 1, "Expected one explicit skew reference path")
                        rf = fields(refs[0])
                        need(len(f) == len(rf) == 14, "Unexpected skew path schema")
                        a, b = arrival(row, source_port), arrival(refs[0], source_port)
                        need(f[6] == rf[6] == launch_clock and f[7] == rf[7] == reference_clock, "Mixed source/capture clock")
                        need(a["source_edge"] == b["source_edge"], "Skew reference is a different physical source edge")
                        need(f[5] in PORTS and rf[5] in PORTS and f[5] not in seen, "Missing, repeated or non-TX endpoint")
                        need(number(f[9]) <= 2.5 and number(rf[9]) <= 2.5, "TX internal path exceeds 2.500 ns")
                        expected = -0.05 if is_max else 0.05
                        need(abs(a["uncertainty_ns"] - expected) < EPS and abs(b["uncertainty_ns"] + expected) < EPS,
                             "Unrecognized uncertainty: cannot cancel assumed common jitter")
                        cpr = number(f[13])
                        physical = a["arrival_ns"] - b["arrival_ns"] - cpr
                        raw = number(f[12]) - number(rf[12]) - cpr
                        need(abs(abs(raw) - abs(physical) - 0.1) < EPS, "Native and physical skew do not differ by exactly common jitter")
                        need(abs(physical) <= 0.3 + 0.00001, "Physical TX source spread exceeds 0.300 ns")
                        seen.add(f[5]); edges.add(a["source_edge"])
                        case["paths"].append({"group": group_name, "port": f[5], "reference_port": rf[5],
                            "arrival_ns": a["arrival_ns"], "reference_arrival_ns": b["arrival_ns"],
                            "relative_cpr_ns": cpr, "signed_physical_difference_ns": round(physical, 3),
                            "native_with_system_jitter_ns": round(raw, 3), "output_edge": a["output_edge"]})
                        if f[5] == "PHY0_TXC":
                            txc_envelopes[corner, a["source_edge"], "max" if is_max else "min"] = a
                    need(seen == PORTS, "Each MaxSkew group must cover all six TX pins")
                need(len(edges) == 1 and len(groups) == 2 and len(case["paths"]) == 12, "Incomplete edge envelope")
                case["source_edge"] = edges.pop()
                key = corner, case["source_edge"]
                need(key not in coverage, "Duplicate corner/source-edge case")
                coverage.add(key)
                case["physical_max_ns"] = max(abs(p["signed_physical_difference_ns"]) for p in case["paths"])
                need(abs(case["native_actual_ns"] - case["physical_max_ns"] - 0.1) < EPS, "Missing worst native skew path")
                case["physical_margin_ns"] = round(0.3 - case["physical_max_ns"], 3)
                result["cases"].append(case)
        need(coverage == {(c, e) for c in ("slow", "fast") for e in ("r", "f")}, "Missing one of four corner/edge cases")
        result["skew_status"] = "PASS"
        # The max/min paths bound all output transitions, including the actual
        # D0=1 (rising) / D1=0 (falling) TXC transitions. Do not falsely call an
        # unreachable worst transition the actual propagated clock waveform.
        duty_cases = []
        for corner in ("slow", "fast"):
            rmin, rmax, fmin, fmax = [txc_envelopes[corner, e, m]["arrival_ns"]
                                     for e, m in (("r", "min"), ("r", "max"), ("f", "min"), ("f", "max"))]
            lower_delta = fmin - rmax - edge_jitter_budget_ns
            upper_delta = fmax - rmin + edge_jitter_budget_ns
            high_min = 8 * input_duty_min_percent / 100 + lower_delta
            high_max = 8 * input_duty_max_percent / 100 + upper_delta
            duty_cases.append({"corner": corner, "rise_arrival_envelope_ns": [rmin, rmax],
                               "fall_arrival_envelope_ns": [fmin, fmax], "cross_edge_cppr_removed_ns": 0,
                               "high_width_envelope_ns": [round(high_min, 3), round(high_max, 3)],
                               "low_width_envelope_ns": [round(8-high_max, 3), round(8-high_min, 3)],
                               "pass": high_min >= 3.6 and high_max <= 4.4})
        duty_pass = all(c["pass"] for c in duty_cases)
        result["duty"] = {"status": "PASS" if duty_pass else "FAIL", "period_ns": 8.0,
             "input_duty_percent": [input_duty_min_percent, input_duty_max_percent],
             "required_output_duty_percent": [45, 55], "edge_jitter_budget_ns": edge_jitter_budget_ns,
             "input_specification": "YSO230LR Output Symmetry 45 to 55%; https://yxcxtal.com/product/yso230lr.html",
             "method": "Conservative all-transition arrival envelopes; no unproven cross-edge CPPR cancellation",
             "cases": duty_cases}
        if sdf_paths is not None:
            fdc = constraints.read_text(encoding="utf-8")
            need(re.search(r"create_clock\s+-name\s+ref125\s+-period\s+8\.0+\s+\[get_ports\s+\{?sys_clk_125_p\}?\]", fdc),
                 "Unverified physical 125 MHz PLL reference")
            need(re.search(r"create_generated_clock[^\n]*-name\s+eth250\s[^\n]*-multiply_by\s+2\s", fdc),
                 "Unverified 250 MHz PLL clock constraint")
            need(re.search(r"create_generated_clock[^\n]*-name\s+eth125\s[^\n]*-divide_by\s+2\s", fdc),
                 "Unverified single-edge divide-by-two clock constraint")
            result["duty"] = shaped_clock_duty(sdf_paths, netlist_paths)
            for case in result["duty"]["cases"]:
                physical_rows = txc_envelopes[case["corner"], "r", "max"]["rows"]
                locations = {r[0].split("/", 1)[0] for r in physical_rows if "/" in r[0]}
                for key in ("pll_cell", "divider_cell", "clock_buffer_cell", "txc_oddr_cell", "txc_pad_cell"):
                    need(case[key].split("/", 1)[0] in locations, "SDF/netlist clock path does not match this RTR implementation")
            duty_pass = result["duty"]["status"] == "PASS"
        need(duty_pass, "TXC 45..55 percent duty cannot be proved from the board source range and physical propagation envelopes")
        result["status"] = "PASS"
    except (AuditError, ET.ParseError, ValueError, IndexError, TypeError) as exc:
        result["errors"].append(str(exc))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report-db", required=True, type=Path)
    p.add_argument("--constraints", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--reference-clock", default="tx_pad_ref")
    p.add_argument("--slow-sdf", type=Path)
    p.add_argument("--fast-sdf", type=Path)
    p.add_argument("--slow-netlist", type=Path)
    p.add_argument("--fast-netlist", type=Path)
    args = p.parse_args()
    try:
        supplied = [args.slow_sdf, args.fast_sdf, args.slow_netlist, args.fast_netlist]
        need(not any(supplied) or all(supplied), "Provide all four SDF/netlist inputs")
        result = audit_tx_source(args.report_db, args.constraints, reference_clock=args.reference_clock,
            sdf_paths={"slow": args.slow_sdf, "fast": args.fast_sdf} if all(supplied) else None,
            netlist_paths={"slow": args.slow_netlist, "fast": args.fast_netlist} if all(supplied) else None)
    except (OSError, ValueError) as exc:
        result = {"schema_version": 1, "status": "FAIL", "errors": [str(exc)], "cases": [], "duty": {"status": "FAIL"}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "errors": result["errors"], "output": str(args.output)}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
