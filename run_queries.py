import argparse
import subprocess
import os
os.environ['JENA_HOME'] = os.path.abspath(os.path.join("tools", "apache-jena-6.0.0"))

DATA_FILE = "data/eu_ai_act_final.ttl"
QUERY_FILE = "om_n_om/Queries.rq"

ARQ_CMD = os.path.join(
    os.environ["JENA_HOME"],
    "bat" if os.name == "nt" else "bin",
    "arq.bat" if os.name == "nt" else "arq",
)


def split_queries(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    queries = content.split("# ---")
    result = []

    for q in queries:
        q = q.strip()
        if not q:
            continue
        result.append(q)

    return result


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run all competency queries against a Turtle data file."
    )
    parser.add_argument(
        "--datafile",
        default=DATA_FILE,
        help=f"Path to the Turtle data file to query (default: {DATA_FILE})",
    )
    return parser.parse_args()


def run_query(query_text, index, data_file):
    temp_file = f"temp_query_{index}.rq"

    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(query_text)

    print(f"\n=== Running CQ{index} ===")

    result = subprocess.run(
        [ARQ_CMD, "--data", data_file, "--query", temp_file],
        capture_output=True,
        text=True
    )

    print(result.stdout)

    if result.stderr:
        print("ERROR:", result.stderr)


def main():
    args = parse_args()
    queries = split_queries(QUERY_FILE)

    for i, query in enumerate(queries, start=1):
        run_query(query, i, args.datafile)
    
    # delete all temp query files
    for i in range(1, len(queries) + 1):
        temp_file = f"temp_query_{i}.rq"
        if os.path.exists(temp_file):
            os.remove(temp_file)


if __name__ == "__main__":
    main()
