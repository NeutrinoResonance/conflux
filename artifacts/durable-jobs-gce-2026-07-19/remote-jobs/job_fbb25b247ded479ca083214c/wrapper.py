import json,os,signal,subprocess,sys,time
p=json.loads('{"command":"python3 -c \\"import sys, time; [print(f\'heartbeat {i}\', flush=True) or time.sleep(1) for i in range(1, 91)]\\"","command_sha256":"41898cd908ed7bab68af6feb3c9ab4b8055895c8c294b6a64218a6f2f56df1c9","cwd":"/tmp/llm-super-agent","job_id":"job_fbb25b247ded479ca083214c","label":"heartbeat-90s","root":"/tmp/llm-super-agent/.jobs/job_fbb25b247ded479ca083214c","timeout_s":120}'); root=p['root']
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
