import secrets
import string

SAFE_SYMBOLS = '!@#$%^&*-_=+'

def generate_password(length=16, upper=True, lower=True, digits=True, symbols=True):
    if length < 4:
        raise ValueError("Password length must be at least 4")
    
    char_pool = ''
    required = []
    
    if upper:
        char_pool += string.ascii_uppercase
        required.append(secrets.choice(string.ascii_uppercase))
    if lower:
        char_pool += string.ascii_lowercase
        required.append(secrets.choice(string.ascii_lowercase))
    if digits:
        char_pool += string.digits
        required.append(secrets.choice(string.digits))
    if symbols:
        char_pool += SAFE_SYMBOLS
        required.append(secrets.choice(SAFE_SYMBOLS))
    
    if not char_pool:
        raise ValueError("At least one character type must be selected")
    
    remaining = length - len(required)
    password_chars = required + [secrets.choice(char_pool) for _ in range(remaining)]
    secrets.SystemRandom().shuffle(password_chars)
    
    return ''.join(password_chars)
