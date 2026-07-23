python3 -c "
import os, sys, time

artifact_dir = os.environ['LLM_SUPER_ARTIFACT_DIR']

# 5 stdout lines, each >= 100 bytes
for i in range(1, 6):
    line = f'[STDOUT {i:02d}] ' + 'X' * 85 + f' END_STDOUT_{i:02d}'
    sys.stdout.write(line + '\n')
    sys.stdout.flush()
    time.sleep(0.3)

# 3 stderr lines, each >= 100 bytes
for i in range(1, 4):
    line = f'[STDERR {i:02d}] ' + 'Y' * 85 + f' END_STDERR_{i:02d}'
    sys.stderr.write(line + '\n')
    sys.stderr.flush()
    time.sleep(0.3)

# Write result.txt
result_path = os.path.join(artifact_dir, 'result.txt')
with open(result_path, 'w') as f:
    f.write('cursor-proof result written\n')
"