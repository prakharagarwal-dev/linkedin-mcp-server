"""Run either the public CLI or the private shared-host process."""

from linkedin_mcp.cli.main import main
from linkedin_mcp.host.manager import host_process_main, internal_host_requested

if __name__ == "__main__":
    if internal_host_requested():
        host_process_main()
    else:
        main()
