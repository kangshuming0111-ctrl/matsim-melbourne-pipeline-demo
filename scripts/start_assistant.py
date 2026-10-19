"""Start the owned local model and reuse/start MATSim's API; no simulation."""
from wrapper.ai_provider import ensure_service
from wrapper.server import start_server, BASE_URL

def main():
    ensure_service()
    pid = start_server()
    print(f'MATSim AI assistant ready (API PID {pid}): {BASE_URL}/assistant')

if __name__ == '__main__':
    main()
