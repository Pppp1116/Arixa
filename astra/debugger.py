import argparse, bdb, runpy

class AstraDebugger(bdb.Bdb):
    def user_line(self, frame):
        print(f"break {frame.f_code.co_filename}:{frame.f_lineno}")
        self.set_continue()

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument('script'); ns=p.parse_args(argv)
    d=AstraDebugger(); d.runctx("runpy.run_path(script, run_name='__main__')", {'runpy':runpy,'script':ns.script}, {})


if __name__ == "__main__":
    main()
