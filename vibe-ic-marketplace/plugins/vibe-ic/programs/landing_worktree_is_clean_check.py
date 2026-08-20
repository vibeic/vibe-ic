import subprocess, sys
out = subprocess.run(['git','-C',sys.argv[1],'status','--porcelain',
                      '--untracked-files=no'],
                     capture_output=True, text=True).stdout
print(out)
raise SystemExit(1 if out.strip() else 0)
