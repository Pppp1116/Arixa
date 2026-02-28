import subprocess, sys, time

def run(cmd):
    t=time.time(); subprocess.check_call(cmd); return time.time()-t

if __name__=='__main__':
    astra = run([sys.executable, '-m', 'astra.cli', 'build', 'examples/fib.astra', '-o', 'build/fib.py'])
    py = run([sys.executable, 'build/fib.py'])
    print({'astra_build_s':astra, 'astra_run_s':py, 'c_estimate_note':'compile C analog separately', 'rust_estimate_note':'compile Rust analog separately'})
