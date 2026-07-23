import json,os,signal,subprocess,sys,time
p=json.loads('{"command":"for i in 1 2 3; do echo \\"phase $i\\"; sleep 1; done","command_sha256":"dce3d631a75d65ae8d4aa983fb101f3f8325af7c5099d317d1a851be27e5d7cc","cwd":"/tmp/llm-super-agent","job_id":"job_2b83d93e7d304f31aeb0b301","label":"phase-123","root":"/tmp/llm-super-agent/.jobs/job_2b83d93e7d304f31aeb0b301","timeout_s":30}'); root=p['root']
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
