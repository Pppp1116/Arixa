"""CPU fallback backend that emulates GPU thread launches for ASTRA."""

from __future__ import annotations


class StubBackend:
    """Deterministic host-side GPU emulator backend."""

    name = "stub-cpu"

    def available(self) -> bool:
        return True

    def device_count(self) -> int:
        return 1

    def device_name(self, index: int) -> str:
        if int(index) != 0:
            raise IndexError(f"stub device index out of range: {index}")
        return "ASTRA GPU Stub (CPU)"

    def launch(self, kernel, grid_size: int, block_size: int, args: list, runtime) -> None:
        total_threads = max(0, int(grid_size))
        block_dim = max(1, int(block_size))
        grid_dim = 0 if total_threads == 0 else (total_threads + block_dim - 1) // block_dim
        for global_id in range(total_threads):
            thread_id = global_id % block_dim
            block_id = global_id // block_dim
            runtime._set_launch_context(  # pylint: disable=protected-access
                global_id=global_id,
                thread_id=thread_id,
                block_id=block_id,
                block_dim=block_dim,
                grid_dim=grid_dim,
            )
            try:
                kernel(*args)
            finally:
                runtime._clear_launch_context()  # pylint: disable=protected-access
