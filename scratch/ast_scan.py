import ast
import os
import re

ASYNC_METHODS = {
    'send', 'reply', 'edit', 'delete', 'add_roles', 'remove_roles',
    'add_reaction', 'remove_reaction', 'purge', 'ban', 'kick',
    'fetch_message', 'fetch_user', 'fetch_channel', 'fetch_guild',
    'defer', 'respond', 'followup'
}

TOKEN_REGEX = re.compile(r'[MN][a-zA-Z\d]{23,}\.[\w-]{6}\.[\w-]{27,}')

def scan_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Security check for tokens
    for match in TOKEN_REGEX.finditer(content):
        # We don't print the token, just the location
        line_no = content[:match.start()].count('\n') + 1
        print(f"[SECURITY] {filepath}:{line_no} Hardcoded bot token found!")

    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError as e:
        print(f"[SYNTAX] {filepath}:{e.lineno} {e}")
        return

    for node in ast.walk(tree):
        # Bare except
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                print(f"[LOGIC] {filepath}:{node.lineno} Bare 'except:' clause")
        
        # Missing await
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in ASYNC_METHODS:
                    # Need to check if this Call is the value of an Await
                    # This is tricky without parent pointers, so we use an alternative approach.
                    pass

    # Better way to find missing awaits: Find all Await nodes and keep track of their Call children.
    # Then find all Call nodes to async methods that are NOT in the awaited set.
    class AwaitVisitor(ast.NodeVisitor):
        def __init__(self):
            self.awaited_calls = set()
            self.all_async_calls = []

        def visit_Await(self, node):
            if isinstance(node.value, ast.Call):
                self.awaited_calls.add(node.value)
            self.generic_visit(node)

        def visit_Call(self, node):
            if isinstance(node.func, ast.Attribute) and node.func.attr in ASYNC_METHODS:
                self.all_async_calls.append(node)
            self.generic_visit(node)

    visitor = AwaitVisitor()
    visitor.visit(tree)

    for call in visitor.all_async_calls:
        if call not in visitor.awaited_calls:
            # Maybe it's awaited later or gathered, but flag it for review
            # Check if it's inside a list comprehension or variable assignment.
            # For simplicity, we just print a warning.
            print(f"[ASYNC] {filepath}:{call.lineno} Call to '{call.func.attr}()' is not directly awaited.")


for root, _, files in os.walk('.'):
    if '.venv' in root or '__pycache__' in root or 'scratch' in root:
        continue
    for file in files:
        if file.endswith('.py'):
            if file == 'main.py':
                scan_file('scratch/main_fixed.py')
            else:
                scan_file(os.path.join(root, file))
