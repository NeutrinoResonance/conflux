import json,os,signal,subprocess,sys,time
p=json.loads('{"command":"/tmp/llm-super-agent/venv/bin/python -m unittest discover -s tests -v","command_sha256":"eb8a2977a3c5150192289446b841920ebf8f606c874242ecfffe1e8a92fa8b43","cwd":"/tmp/llm-super-agent/repo","job_id":"job_068e79ff6ee145339c12a96d","label":"unittest-full-suite","root":"/tmp/llm-super-agent/.jobs/job_068e79ff6ee145339c12a96d","timeout_s":900}'); root=p['root']
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
