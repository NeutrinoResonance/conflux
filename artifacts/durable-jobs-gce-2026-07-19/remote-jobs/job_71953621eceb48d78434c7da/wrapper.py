import json,os,signal,subprocess,sys,time
p=json.loads('{"command":"python3 -c \\"\\nimport sys, time\\nfor i in range(1, 121):\\n    print(f\'heartbeat {i}\')\\n    sys.stdout.flush()\\n    time.sleep(1)\\n\\"","command_sha256":"51018fe9cb127aef3a69aff04d05efe0fc3cc353d7720510e202daaf233573e6","cwd":"/tmp/llm-super-agent","job_id":"job_71953621eceb48d78434c7da","label":"heartbeat-cancel-test","root":"/tmp/llm-super-agent/.jobs/job_71953621eceb48d78434c7da","timeout_s":180}'); root=p['root']
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
