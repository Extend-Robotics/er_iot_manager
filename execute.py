import subprocess

def run_job(job_id, job_document):
    try:
        print(f"Executing job {job_id} with document: {job_document}")
        
        # Extract steps from the job document
        steps = job_document.get('steps', [])
        
        for step in steps:
            action = step.get('action', {})
            if action.get('type') == 'runCommand':
                command = action['input'].get('command')
                
                if command:
                    print(f"Running command: {command}")
                    # Execute the command
                    result = subprocess.run(command, shell=True, capture_output=True, text=True)
                    print(f"Command output: {result.stdout}")
                    if result.returncode != 0:
                        print(f"Command failed with error: {result.stderr}")
                        return False  # or raise an error, depending on handling
                else:
                    print("No command found in job step.")
                    
    except Exception as e:
        print(f"Failed to execute job {job_id} due to: {e}")
        raise e
