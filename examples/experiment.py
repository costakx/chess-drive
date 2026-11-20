import sys
sys.path.insert(0, "src")

from chessdrive.file_io import read_file, write_file

data = read_file("examples/sample.txt")
write_file("examples/output.txt", data)

print(read_file("examples/output.txt") == data)
