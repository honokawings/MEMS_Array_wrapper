import os
import argparse

def generate_modelsim_filelist(directory, output_file, relative_to=None, extensions=None):
    """
    生成ModelSim格式的文件列表

    :param directory: 要搜索的根目录
    :param output_file: 输出文件路径
    :param relative_to: 相对路径基准目录
    :param extensions: 包含的文件扩展名列表
    """
    # 确保目录路径标准化
    directory = os.path.abspath(directory)

    # 设置相对路径基准
    base_dir = os.path.dirname(os.path.abspath(output_file)) if relative_to is None else relative_to

    # 确保输出目录存在
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"已创建目录: {output_dir}")

    # 默认包含的文件扩展名
    default_extensions = {'.v', '.sv', '.vhd', '.vhdl', '.vho'}
    include_extensions = extensions or default_extensions

    file_count = 0
    if not os.path.isdir(directory):
        raise FileNotFoundError(directory)
    sources = []
    include_dirs = set()
    for root, dirs, files in os.walk(directory):
        dirs[:] = sorted(d for d in dirs if d not in {'.git', '.deps', '.venv', '__pycache__', 'work', 'build'})
        for filename in sorted(files):
            if os.path.splitext(filename)[1].lower() in {'.vh', '.svh'}:
                include_dirs.add(os.path.relpath(root, base_dir).replace('\\', '/'))
            sources.append((root, filename))
    with open(output_file, 'w', encoding='utf-8') as f_out:
        for inc in sorted(include_dirs):
            f_out.write('"+incdir+' + inc + '"\n')
        # Packages must precede modules that import them.
        sources.sort(key=lambda item: (not item[1].endswith(('_pkg.sv', '_package.sv')), item))
        for root, filename in sources:
                # 检查文件扩展名
                ext = os.path.splitext(filename)[1].lower()
                if ext in {'.vh', '.svh'}:
                    continue
                if include_extensions and ext not in include_extensions:
                    continue

                # 获取文件绝对路径
                full_path = os.path.join(root, filename)

                # 转换为相对路径
                rel_path = os.path.relpath(full_path, base_dir)

                # 替换路径分隔符
                rel_path = rel_path.replace('\\', '/')

                # 写入输出文件
                f_out.write(rel_path + '\n')
                file_count += 1

    return file_count

# 基本用法
# python gen_filelist.py ../riffa -o filelist.f --ext .v .vh
# python gen_filelist.py ../rtl -o modelsim_filelist.f --ext .v .vh .vp

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='生成ModelSim格式的文件列表')
    parser.add_argument('directory', help='要扫描的根目录')
    parser.add_argument('-o', '--output', default='modelsim_filelist.f',
                        help='输出文件路径 (默认: modelsim_filelist.f)')
    parser.add_argument('--relative', metavar='BASE_DIR',
                        help='生成相对路径的基准目录（默认使用输出文件所在目录）')
    parser.add_argument('--ext', nargs='+', default=None,
                        help='包含的文件扩展名（空格分隔，例如: .v .sv .vhd）')

    args = parser.parse_args()

    # 处理扩展名参数
    extensions = set(ext.lower() for ext in args.ext) if args.ext else None

    file_count = generate_modelsim_filelist(
        directory=args.directory,
        output_file=args.output,
        relative_to=args.relative,
        extensions=extensions
    )

    print(f"\n已生成文件列表: {os.path.abspath(args.output)}")
    print(f"扫描目录: {os.path.abspath(args.directory)}")
    print(f"包含文件数量: {file_count}")
    if args.relative:
        print(f"相对路径基准: {args.relative}")
    if extensions:
        print(f"包含的扩展名: {', '.join(extensions)}")
