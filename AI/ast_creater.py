import ast
import json


class SymbolExtractor(ast.NodeVisitor):
    def __init__(self):
        self.metadata = []

    def visit_FunctionDef(self, node):
        # 1. Extract Basic Info
        func_data = {
            "type": "function",
            "name": node.name,
            "line_start": node.lineno,
            "line_end": getattr(node, "end_lineno", node.lineno),
            "args": [arg.arg for arg in node.args.args],
            "calls": [],
            "accessed_attributes": [],
            "docstring": ast.get_docstring(node)
        }
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    func_data["calls"].append(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    func_data["calls"].append(child.func.attr)

            elif isinstance(child, ast.Attribute):
                func_data["accessed_attributes"].append(child.attr)

        # Cleanup: Remove duplicates
        func_data["calls"] = list(set(func_data["calls"]))
        func_data["accessed_attributes"] = list(set(func_data["accessed_attributes"]))

        self.metadata.append(func_data)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        # Extract class names to build "Parent-Child" relationships in KG
        class_data = {
            "type": "class",
            "name": node.name,
            "bases": [base.id for base in node.bases if isinstance(base, ast.Name)],
            "line_start": node.lineno
        }
        self.metadata.append(class_data)
        self.generic_visit(node)


def get_code_metadata(source_code: str):

    try:
        tree = ast.parse(source_code)
        extractor = SymbolExtractor()
        extractor.visit(tree)
        return extractor.metadata
    except SyntaxError as e:
        return {"error": f"Invalid Python syntax: {e}"}

if __name__ == "__main__":
    test_code = """
    class UserAuth:
        def login(self, username, password):
            \"\"\"Handles user login logic.\"\"\"
            user = database.get_user(username)
            if user.check_password(password):
                print(user.id)
                x=100
                f=10
                h=x*f
                user.id=h
                return generate_token(user.id)
            return None
    """

    structure = get_code_metadata(test_code)
    print(json.dumps(structure, indent=2))
