import os
import glob

api_dir = "/Users/shreyas/Desktop/26250/backend/app/api"
files = glob.glob(f"{api_dir}/*.py")

for file in files:
    with open(file, "r") as f:
        content = f.read()
    
    if "def _audit(" in content:
        print(f"Refactoring {file}")
        
        # We need to replace the local _audit function with an import
        # or just make the local _audit call log_audit.
        
        # It's safer to just replace the body of _audit
        if "from backend.app.services.audit import log_audit" not in content:
            content = "from backend.app.services.audit import log_audit\n" + content
            
        import re
        # Find def _audit(db, user...): and replace its body
        # Since signatures vary slightly, we will regex replace the function body
        pattern = re.compile(r"def _audit\([^\)]+\):\s+(?:(?:.|\n)(?!def |@|class ))+", re.MULTILINE)
        
        def replacement(match):
            sig = match.group(0).split(":")[0]
            return sig + ":\n    log_audit(db, user, action, resource, result, ip, details)\n\n\n"
        
        new_content = pattern.sub(replacement, content)
        
        with open(file, "w") as f:
            f.write(new_content)
