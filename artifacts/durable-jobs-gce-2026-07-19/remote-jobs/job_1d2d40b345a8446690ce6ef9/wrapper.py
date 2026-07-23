import json,os,signal,subprocess,sys,time
p=json.loads('{"command":"python3 -c \\"\\nimport os, sys, time\\n\\nartifact_dir = os.environ[\'LLM_SUPER_ARTIFACT_DIR\']\\n\\n# 5 stdout lines, each >= 100 bytes\\nfor i in range(1, 6):\\n    line = f\'[STDOUT {i:02d}] \' + \'X\' * 85 + f\' END_STDOUT_{i:02d}\'\\n    sys.stdout.write(line + \'\\\\n\')\\n    sys.stdout.flush()\\n    time.sleep(0.3)\\n\\n# 3 stderr lines, each >= 100 bytes\\nfor i in range(1, 4):\\n    line = f\'[STDERR {i:02d}] \' + \'Y\' * 85 + f\' END_STDERR_{i:02d}\'\\n    sys.stderr.write(line + \'\\\\n\')\\n    sys.stderr.flush()\\n    time.sleep(0.3)\\n\\n# Write result.txt\\nresult_path = os.path.join(artifact_dir, \'result.txt\')\\nwith open(result_path, \'w\') as f:\\n    f.write(\'cursor-proof result written\\\\n\')\\n\\"","command_sha256":"96690b8c5cb84dfcf484d54d96e1d6bec9a1623ee08f2b13ca9c0e48a74015dd","cwd":"/tmp/llm-super-agent","job_id":"job_1d2d40b345a8446690ce6ef9","label":"cursor-artifact-test","root":"/tmp/llm-super-agent/.jobs/job_1d2d40b345a8446690ce6ef9","timeout_s":30}'); root=p['root']
def atomic(name,value):
 t=os.path.join(root,name+'.tmp'); open(t,'w').write(str(value)); os.replace(t,os.path.join(root,name))
atomic('started_at',time.time())
out=open(os.path.join(root,'stdout.log'),'ab',buffering=0); err=open(os.path.join(root,'stderr.log'),'ab',buffering=0)
env=os.environ.copy(); env['LLM_SUPER_JOB_ID']=p['job_id']; env['LLM_SUPER_JOB_DIR']=root; env['LLM_SUPER_ARTIFACT_DIR']=os.path.join(root,'artifacts')
child=subprocess.Popen(['/usr/bin/timeout','--signal=TERM','--kill-after=5',str(p['timeout_s'])+'s','/bin/sh',os.path.join(root,'command.sh')],cwd=p['cwd'],stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True,env=env)
atomic('workload.pid',child.pid)
while child.poll() is None:
 atomic('heartbeat',time.time()); time.sleep(1)
code=child.wait(); code=128+(-code) if code < 0 else code
atomic('heartbeat',time.time()); atomic('exit_code',code); atomic('ended_at',time.time())
out.close(); err.close()
