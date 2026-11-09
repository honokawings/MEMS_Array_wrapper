from pathlib import Path
import hashlib,json
root=Path(__file__).resolve().parent
manifest=json.loads((root/"SNAPSHOT_MANIFEST.json").read_text(encoding="utf-8"))
for record in manifest["files"]:
    data=(root/record["path"]).read_bytes()
    assert len(data)==record["bytes"],record["path"]
    assert hashlib.sha256(data).hexdigest()==record["sha256"],record["path"]
canonical="\n".join(r["path"]+" "+r["sha256"] for r in sorted(manifest["files"],key=lambda r:r["path"]))+"\n"
assert hashlib.sha256(canonical.encode()).hexdigest()==manifest["source_content_sha256"]
portable=json.loads((root/"SOURCEPACK_PORTABLE.json").read_text(encoding="utf-8"))
assert len(portable["sources"])==105
assert all((root/x["path"]).is_file() for x in portable["sources"])
assert all((root/x).is_file() for x in portable["constraints"])
assert all((root/p).is_file() for closure in manifest["idf_closures"] for p in closure["children"])
print(json.dumps({"status":"PASS","files":len(manifest["files"]),"source_content_sha256":manifest["source_content_sha256"]}))
