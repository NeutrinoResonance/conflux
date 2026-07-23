python3 -c "
import sys, time
for i in range(1, 121):
    print(f'heartbeat {i}')
    sys.stdout.flush()
    time.sleep(1)
"