"""Small debugger wrapper for running generated Python with breakpoints."""

import argparse, bdb, runpy

class AstraDebugger(bdb.Bdb):
    """Data container used by debugger.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    def user_line(self, frame):
        """Debugger callback invoked when execution reaches a traced source line.
        
        Parameters:
            frame: Input value used by this function.
        
        Returns:
            Value produced by the function, if any.
        """
        print(f"break {frame.f_code.co_filename}:{frame.f_lineno}")
        self.set_continue()

def main(argv=None):
    """CLI-style entrypoint for this module.
    
    Parameters:
        argv: Optional CLI arguments passed instead of process argv.
    
    Returns:
        Value produced by the function, if any.
    """
    p=argparse.ArgumentParser(); p.add_argument('script'); ns=p.parse_args(argv)
    d=AstraDebugger(); d.runctx("runpy.run_path(script, run_name='__main__')", {'runpy':runpy,'script':ns.script}, {})


if __name__ == "__main__":
    main()
