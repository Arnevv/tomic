import os
import subprocess

# === CONFIG ===
PROTOC_PATH = r"C:\Program Files (x86)\Protoc\bin\protoc.exe"  # eventueel aanpassen
PROJECT_ROOT = os.path.dirname(__file__)
PROTO_SRC = os.path.join(PROJECT_ROOT, "tomic", "ibkr-original-protofiles")
PYTHON_OUT = os.path.join(PROJECT_ROOT, "tomic", "ibapi", "protobuf")

# === CHECKS ===
if not os.path.exists(PROTOC_PATH):
    print(f"❌ protoc niet gevonden op: {PROTOC_PATH}")
    exit(1)

if not os.path.exists(PROTO_SRC):
    print(f"❌ .proto-bestandenmap bestaat niet: {PROTO_SRC}")
    exit(1)

if not os.path.exists(PYTHON_OUT):
    os.makedirs(PYTHON_OUT)
    print(f"📁 Aangemaakt: {PYTHON_OUT}")

init_file = os.path.join(PYTHON_OUT, "__init__.py")
if not os.path.exists(init_file):
    with open(init_file, "w", encoding="utf-8") as f:
        f.write("# Init for protobuf package\n")
    print("➕ __init__.py toegevoegd aan protobuf-map")

# === GENERATE ===
proto_files = [f for f in os.listdir(PROTO_SRC) if f.endswith(".proto")]
if not proto_files:
    print("⚠️ Geen .proto-bestanden gevonden in bronmap.")
    exit(0)

print(f"🔄 Genereren van {len(proto_files)} bestand(en):\n")

for proto_file in proto_files:
    input_path = os.path.join(PROTO_SRC, proto_file)
    cmd = [
        PROTOC_PATH,
        f"--proto_path={PROTO_SRC}",
        f"--python_out={PYTHON_OUT}",
        proto_file
    ]
    try:
        subprocess.run(cmd, check=True, cwd=PROTO_SRC)
        print(f"✅ {proto_file} → {os.path.basename(proto_file).replace('.proto', '_pb2.py')}")
    except subprocess.CalledProcessError as e:
        print(f"❌ fout bij {proto_file}: {e}")
