import pexpect
import sys

def main():
    print("Connecting to server...")
    child = pexpect.spawn('ssh -o StrictHostKeyChecking=no admin123@homeihc-ai-server', encoding='utf-8')
    child.logfile = sys.stdout
    
    try:
        i = child.expect(['(?i)password:', '(?i)passphrase', pexpect.EOF, pexpect.TIMEOUT], timeout=10)
        if i == 0:
            child.sendline('P@ssw0rd')
        elif i == 1:
            child.sendline('P@ssw0rd')
        elif i == 2:
            print("EOF")
            return
        elif i == 3:
            print("TIMEOUT")
            return
            
        child.expect(r'\$')
        
        # Run diagnostic commands
        commands = [
            'pwd',
            'ls -la ~/opt/crm',
            'cd ~/opt/crm && git status',
            'cd ~/opt/crm && docker ps',
            'cd ~/opt/crm && docker compose ls'
        ]
        
        for cmd in commands:
            print(f"\n--- Running: {cmd} ---")
            child.sendline(cmd)
            child.expect(r'\$')
            
        child.sendline('exit')
        child.expect(pexpect.EOF)
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    main()
