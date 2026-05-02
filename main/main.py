import sys

from agent.agent import run_agent


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m main.main \"your question here\"")
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    answer = run_agent(question)
    print(f"\n[answer]\n{answer}")


if __name__ == "__main__":
    main()
