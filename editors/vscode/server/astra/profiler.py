"""Simple profiling runner for generated Python programs."""

import argparse, cProfile, pstats

def main(argv=None):
    """CLI-style entrypoint for this module.
    
    Parameters:
        argv: Optional CLI arguments passed instead of process argv.
    
    Returns:
        Value produced by the routine, if any.
    """
    p=argparse.ArgumentParser(); p.add_argument('script'); ns=p.parse_args(argv)
    if '..' in ns.script:
        raise Exception('Invalid file path')
    prof=cProfile.Profile(); prof.enable(); exec(open(ns.script).read(), {'__name__':'__main__'}); prof.disable()
    pstats.Stats(prof).sort_stats('cumtime').print_stats(20)


if __name__ == "__main__":
    main()
