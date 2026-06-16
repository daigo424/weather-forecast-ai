import socket


def _is_debug_server_ready(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.1):
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False


def run_debug_server() -> bool:
    is_debug = False
    try:
        import pydevd_pycharm

        try:
            if _is_debug_server_ready("localhost", 5678):
                pydevd_pycharm.settrace("localhost", port=5678, stdout_to_server=True, stderr_to_server=True, suspend=False)
                is_debug = True
        except (ConnectionRefusedError, TimeoutError, Exception):
           print("⚠️　デバッグサーバーに接続できませんでした（スキップします）")
    except ImportError:
        print("pydevd_pycharm がインストールされていません")
    finally:
        if is_debug:
            print("🐛　------ Start Debugging ------")
        else:
            print("🦶　------ Start ------")

    return is_debug
