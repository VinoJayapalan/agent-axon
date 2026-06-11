import argparse
from axon.agents.dev.orchestrator import run_agent


def main() -> None:
    parser = argparse.ArgumentParser(description="Axon developer agent")
    parser.add_argument("requirement", help="Requirement change to implement")
    args = parser.parse_args()

    result = run_agent(args.requirement)
    print(result)


if __name__ == "__main__":
    main()