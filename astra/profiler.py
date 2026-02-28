import argparse, cProfile, pstats

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument('script'); ns=p.parse_args(argv)
    prof=cProfile.Profile(); prof.enable(); exec(open(ns.script).read(), {'__name__':'__main__'}); prof.disable()
    pstats.Stats(prof).sort_stats('cumtime').print_stats(20)
