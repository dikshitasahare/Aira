"""
AIRA Tools — Weather, Calculator, Python Interpreter
"""
import re
import math
import json
import sys
import io
import traceback
import threading
import urllib.request
import urllib.error
import urllib.parse
from django.conf import settings


# CALCULATOR

def run_calculator(expression: str) -> dict:
    try:
        expr = expression.strip()
        expr = expr.replace('^', '**')
        expr = expr.replace('x', '*')

        if not re.match(r'^[\d\s\+\-\*\/\(\)\.\,\%\*\^sqrtpicosintanlogabsroundfloorceile]+$', expr.lower()):
            expr = re.sub(r'[^0-9\s\+\-\*\/\(\)\.\%\*]', '', expr)

        safe_dict = {
            'sqrt': math.sqrt, 'pi': math.pi, 'e': math.e,
            'sin': math.sin, 'cos': math.cos, 'tan': math.tan,
            'log': math.log, 'log10': math.log10, 'log2': math.log2,
            'abs': abs, 'round': round, 'floor': math.floor,
            'ceil': math.ceil, 'pow': math.pow, 'factorial': math.factorial,
        }

        result = eval(expr, {"__builtins__": {}}, safe_dict)

        if isinstance(result, float):
            if result == int(result):
                result_str = str(int(result))
            else:
                result_str = f"{result:.6f}".rstrip('0').rstrip('.')
        else:
            result_str = str(result)

        return {
            'success': True,
            'expression': expression,
            'result': result,
            'formatted': f"{expression} = {result_str}"
        }
    except ZeroDivisionError:
        return {'success': False, 'error': 'Division by zero'}
    except Exception as e:
        return {'success': False, 'error': f'Invalid expression: {str(e)}'}


# WEATHER

def get_weather(city: str) -> dict:
    api_key = getattr(settings, 'OPENWEATHER_API_KEY', None)
    if not api_key:
        return {'success': False, 'error': 'OPENWEATHER_API_KEY not set in .env'}

    try:
        city_encoded = urllib.parse.quote(city)
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city_encoded}&appid={api_key}&units=metric"
        req = urllib.request.Request(url, headers={'User-Agent': 'AIRA/1.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))

        return {
            'success': True,
            'city': data['name'],
            'country': data['sys']['country'],
            'temp': round(data['main']['temp']),
            'feels_like': round(data['main']['feels_like']),
            'humidity': data['main']['humidity'],
            'description': data['weather'][0]['description'].capitalize(),
            'wind_speed': data['wind']['speed'],
            'visibility': data.get('visibility', 0) // 1000,
            'icon': data['weather'][0]['icon'],
        }

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {'success': False, 'error': f'City "{city}" not found'}
        return {'success': False, 'error': f'Weather API error: {e.code}'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def format_weather(data: dict) -> str:
    if not data['success']:
        return f"Weather error: {data['error']}"

    return (
        f"WEATHER DATA for {data['city']}, {data['country']}:\n"
        f"- Temperature: {data['temp']}C (feels like {data['feels_like']}C)\n"
        f"- Condition: {data['description']}\n"
        f"- Humidity: {data['humidity']}%\n"
        f"- Wind Speed: {data['wind_speed']} m/s\n"
        f"- Visibility: {data['visibility']} km"
    )


# PYTHON INTERPRETER

SAFE_BUILTINS = {
    'print': print, 'len': len, 'range': range,
    'int': int, 'float': float, 'str': str, 'bool': bool,
    'list': list, 'dict': dict, 'tuple': tuple, 'set': set,
    'abs': abs, 'round': round, 'min': min, 'max': max,
    'sum': sum, 'sorted': sorted, 'reversed': reversed,
    'enumerate': enumerate, 'zip': zip, 'map': map,
    'filter': filter, 'isinstance': isinstance,
    'type': type, 'repr': repr, 'format': format,
    'True': True, 'False': False, 'None': None,
}


def run_python(code: str, timeout: int = 10) -> dict:
    code_lower = code.lower()
    dangerous = [
        'import os', 'import sys', 'import subprocess',
        'open(', '__import__', 'exec(', 'eval(',
        'socket', 'requests', 'urllib', 'shutil',
        'os.', 'sys.', 'subprocess.'
    ]

    for d in dangerous:
        if d in code_lower:
            return {
                'success': False,
                'output': '',
                'error': f'Security: "{d}" is not allowed for safety reasons.',
                'execution_time': 0,
            }

    result = {'output': '', 'error': '', 'success': False, 'execution_time': 0}
    old_stdout = sys.stdout
    old_stderr = sys.stderr

    def execute():
        import time
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        start = time.time()
        try:
            safe_globals = {
                '__builtins__': SAFE_BUILTINS,
                'math': math,
                'json': json,
            }
            exec(compile(code, '<aira>', 'exec'), safe_globals)
            result['output'] = sys.stdout.getvalue()
            result['success'] = True
        except Exception:
            result['error'] = traceback.format_exc()
            result['output'] = sys.stdout.getvalue()
        finally:
            result['execution_time'] = round(time.time() - start, 4)
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    thread = threading.Thread(target=execute)
    thread.daemon = True
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        return {
            'success': False,
            'output': '',
            'error': f'Execution timed out after {timeout} seconds.',
            'execution_time': timeout,
        }

    return result


def format_python_result(result: dict) -> str:
    parts = []
    if result['output']:
        parts.append(f"OUTPUT:\n{result['output'].strip()}")
    if result['error']:
        parts.append(f"ERROR:\n{result['error'].strip()}")
    if not parts:
        parts.append("Code executed successfully (no output)")
    parts.append(f"Execution time: {result['execution_time']}s")
    return '\n\n'.join(parts)


# TOOL DETECTION

def detect_tool_request(message: str) -> dict:
    msg = message.lower().strip()

    # Calculator detection
    calc_patterns = [
        r'calculate\s+(.+)',
        r'compute\s+(.+)',
        r'what is\s+([\d\s\+\-\*\/\(\)\.\^]+)',
        r'solve\s+(.+)',
        r'(\d+[\s]*[\+\-\*\/\^][\s]*[\d\(\)]+.*)',
    ]
    for pattern in calc_patterns:
        match = re.search(pattern, msg)
        if match:
            expr = match.group(1).strip()
            if any(op in expr for op in ['+', '-', '*', '/', '^', 'sqrt', 'sin', 'cos']):
                return {'tool': 'calculator', 'input': expr}

    # Weather detection
    weather_patterns = [
        r'weather\s+(?:in\s+|of\s+|for\s+)?([a-zA-Z\s]+)',
        r'(?:temperature|temp)\s+(?:in\s+)?([a-zA-Z\s]+)',
        r'(?:what\'s|whats|how\'s|hows)\s+(?:the\s+)?weather\s+(?:in\s+|at\s+)?([a-zA-Z\s]+)',
        r'is\s+it\s+(?:raining|hot|cold|sunny)\s+in\s+([a-zA-Z\s]+)',
    ]
    for pattern in weather_patterns:
        match = re.search(pattern, msg)
        if match:
            city = match.group(1).strip().rstrip('?.,!')
            if len(city) > 1:
                return {'tool': 'weather', 'input': city}

    # Python code detection
    if '```python' in message or '```py' in message:
        code_match = re.search(r'```(?:python|py)\n?([\s\S]*?)```', message)
        if code_match:
            return {'tool': 'python', 'input': code_match.group(1).strip()}

    python_patterns = [
        r'run (?:this )?(?:python )?code[:\s]+(.*)',
        r'execute[:\s]+(.*python.*)',
        r'python:\s*(.*)',
    ]
    for pattern in python_patterns:
        match = re.search(pattern, msg, re.DOTALL)
        if match:
            return {'tool': 'python', 'input': match.group(1).strip()}

    return {'tool': None, 'input': None}