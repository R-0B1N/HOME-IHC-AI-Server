import re

def process():
    with open('remote_docker-compose.yml', 'r') as f:
        content = f.read()

    # We will just comment out the services block by block using regex or simple string replacement.
    # Actually, simpler: I'll just write a script that replaces the whole block of those services with empty strings or comments.
    
    # Or just use ruamel.yaml if available?
    import yaml
    
    with open('remote_docker-compose.yml', 'r') as f:
        data = yaml.safe_load(f)
        
    services_to_remove = ['property-dashboard', 'api', 'worker', 'whatsapp_ai_redis', 'whatsapp_ai_db']
    for s in services_to_remove:
        if s in data.get('services', {}):
            del data['services'][s]
            
    with open('remote_docker-compose.yml', 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

if __name__ == '__main__':
    try:
        import yaml
        process()
        print("Success")
    except ImportError:
        print("PyYAML not found")
