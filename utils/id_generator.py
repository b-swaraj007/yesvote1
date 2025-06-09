import random
import string
from datetime import datetime
import uuid

def generate_random_digits(length):
    """Generate a random string of digits of specified length."""
    return ''.join(random.choices(string.digits, k=length))

def generate_voter_id():
    """Generate a voter ID in format: DGV-XXXXXX"""
    random_digits = generate_random_digits(6)
    return f"DGV-{random_digits}"

def generate_event_id():
    """Generate an event ID in format: DGVE-XXXXX"""
    random_digits = generate_random_digits(5)
    return f"DGVE-{random_digits}"

def generate_ballot_id():
    """Generate a ballot ID in format: DGVEB-XXXX"""
    random_digits = generate_random_digits(4)
    return f"DGVEB-{random_digits}"

def generate_receipt_id():
    """Generate a receipt ID in format: DGVCR-XXXXXX"""
    random_digits = generate_random_digits(6)
    return f"DGVCR-{random_digits}"

def verify_id_format(id_string):
    """Verify if an ID string matches any of our ID formats."""
    prefixes = {
        'DGV-': 6,    # Voter ID
        'DGVE-': 5,   # Event ID
        'DGVEB-': 4,  # Ballot ID
        'DGVCR-': 6   # Receipt ID
    }
    
    for prefix, length in prefixes.items():
        if id_string.startswith(prefix):
            # Check if the remaining part is exactly 'length' digits
            remaining = id_string[len(prefix):]
            if len(remaining) == length and remaining.isdigit():
                return True
    return False

def get_id_type(id_string):
    """Get the type of ID from the string."""
    if id_string.startswith('DGV-'):
        return 'voter'
    elif id_string.startswith('DGVE-'):
        return 'event'
    elif id_string.startswith('DGVEB-'):
        return 'ballot'
    elif id_string.startswith('DGVCR-'):
        return 'receipt'
    return None

def generate_id():
    return str(uuid.uuid4()) 