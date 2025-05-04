from flask import Flask, request, jsonify, render_template
import os
import google.generativeai as genai
from dotenv import load_dotenv
import re
import time
import base64
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

# Set up the Flask app
app = Flask(__name__)

# Configure the Gemini API with your API key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in environment variables")

genai.configure(api_key=GEMINI_API_KEY)

# Set up the model
model = genai.GenerativeModel('gemini-1.5-pro')

# Watermarking configuration
WATERMARK_CONFIG = {
    'signature': 'CHATGPT',  # Base signature
    'delimiter': '\u200B',   # Zero-width space as delimiter
    'space': ' ',            # Space character
    'tab': '\t'             # Tab character
}

def generate_watermark(user_id=None, timestamp=None):
    """Generate a watermark string with metadata."""
    timestamp = timestamp or int(time.time())
    user_id = user_id or 'anonymous'
    
    # Create watermark data
    watermark_data = {
        'signature': WATERMARK_CONFIG['signature'],
        'timestamp': timestamp,
        'user_id': user_id,
        'generated_at': datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
    }
    
    # Convert to string and encode
    watermark_str = f"{watermark_data['signature']}:{watermark_data['timestamp']}:{watermark_data['user_id']}"
    encoded = base64.b64encode(watermark_str.encode()).decode()
    
    # Convert to binary
    binary = ''.join(format(ord(c), '08b') for c in encoded)
    
    # Convert binary to spaces and tabs
    watermark = ''.join(WATERMARK_CONFIG['space'] if bit == '0' else WATERMARK_CONFIG['tab'] for bit in binary)
    
    return {
        'watermark': watermark,
        'metadata': watermark_data
    }

def embed_watermark(text, watermark):
    """Embed watermark into text."""
    # Add delimiter and watermark at the end
    return text + WATERMARK_CONFIG['delimiter'] + watermark

def extract_watermark(text):
    """Extract and verify watermark from text."""
    try:
        # Split by delimiter
        parts = text.split(WATERMARK_CONFIG['delimiter'])
        if len(parts) != 2:
            return None
        
        content, watermark = parts
        
        # Convert spaces and tabs back to binary
        binary = ''.join('0' if c == WATERMARK_CONFIG['space'] else '1' for c in watermark)
        
        # Convert binary to string
        encoded = ''.join(chr(int(binary[i:i+8], 2)) for i in range(0, len(binary), 8))
        
        # Decode base64
        decoded = base64.b64decode(encoded).decode()
        
        # Parse watermark data
        signature, timestamp, user_id = decoded.split(':')
        
        if signature != WATERMARK_CONFIG['signature']:
            return None
        
        return {
            'signature': signature,
            'timestamp': int(timestamp),
            'user_id': user_id,
            'generated_at': datetime.fromtimestamp(int(timestamp)).strftime('%Y-%m-%d %H:%M:%S')
        }
    except Exception as e:
        print(f"Watermark extraction error: {str(e)}")  # For debugging
        return None

# Input validation patterns
VALIDATION_PATTERNS = {
    'prompt_injection': [
        # Role manipulation
        r'(?i)(you are|you\'re|you\'ve become|you have become|you must be|you should be|you will be|you are now|you have been|you\'ve been)',
        r'(?i)(ignore|disregard|forget|skip|override|bypass|circumvent) (all |any |the |your |these |those )?(previous |prior |earlier |last |above |below )?(instructions|rules|guidelines|directions|commands|prompts)',
        r'(?i)(from now on|starting now|beginning now|henceforth|hereafter|going forward)',
        r'(?i)(your new|your updated|your modified|your changed|your different) (instructions|rules|guidelines|directions|commands|prompts)',
        r'(?i)(you must|you should|you will|you have to|you need to|you ought to) (now |from now on |henceforth |hereafter )?(ignore|disregard|forget|skip|override|bypass|circumvent)',
        r'(?i)(you are no longer|you are not|you aren\'t|you don\'t have to|you don\'t need to)',
        r'(?i)(you can|you may|you are allowed to|you are permitted to) (now |from now on |henceforth |hereafter )?(ignore|disregard|forget|skip|override|bypass|circumvent)',
        
        # System prompt manipulation
        r'(?i)(system|assistant|model|AI|bot|robot|chatbot) (prompt|instruction|command|directive)',
        r'(?i)(override|bypass|circumvent) (the |this |that |these |those )?(system|assistant|model|AI|bot|robot|chatbot)',
        
        # Context manipulation
        r'(?i)(previous|prior|earlier|last|above|below) (conversation|chat|interaction|session)',
        r'(?i)(ignore|disregard|forget|skip|override|bypass|circumvent) (the |this |that |these |those )?(context|conversation|chat|interaction|session)',
        
        # Output manipulation
        r'(?i)(output|respond|answer|reply) (with|using|in) (the |this |that |these |those )?(following|below|above|next)',
        r'(?i)(do not|don\'t|never) (output|respond|answer|reply)',
        
        # Code execution
        r'(?i)(execute|run|perform|carry out) (the |this |that |these |those )?(code|script|program|command)',
        r'(?i)(eval|exec|system|shell|terminal|command line)',
        
        # Data manipulation
        r'(?i)(modify|change|alter|update|edit) (the |this |that |these |those )?(data|information|content)',
        r'(?i)(delete|remove|erase|clear) (the |this |that |these |those )?(data|information|content)',
        
        # Security bypass
        r'(?i)(bypass|circumvent|override) (the |this |that |these |those )?(security|safety|protection|restriction)',
        r'(?i)(ignore|disregard|forget|skip) (the |this |that |these |those )?(security|safety|protection|restriction)',
        
        # Model behavior manipulation
        r'(?i)(behave|act|respond) (like|as) (a |an |the )?',
        r'(?i)(pretend|imitate|simulate|emulate) (to be |that you are |that you\'re )',
        
        # Chain of thought manipulation
        r'(?i)(think|reason|consider|analyze) (about|through|throughout) (the |this |that |these |those )?',
        r'(?i)(let\'s|let us) (think|reason|consider|analyze)',
        
        # Memory manipulation
        r'(?i)(remember|recall|memorize|store) (the |this |that |these |those )?',
        r'(?i)(forget|erase|clear|delete) (the |this |that |these |those )?(memory|memories)',
        
        # Model identity manipulation
        r'(?i)(you are|you\'re|you have become|you\'ve become) (a |an |the )?',
        r'(?i)(your name|your identity|who you are) (is|are|becomes|has become)',
        
        # Output format manipulation
        r'(?i)(format|structure|organize) (the |this |that |these |those )?(output|response|answer)',
        r'(?i)(output|respond|answer) (in|using|with) (the |this |that |these |those )?(format|structure|organization)',
        
        # Chain of thought injection
        r'(?i)(let\'s|let us) (think|reason|consider|analyze) (step by step|one by one|carefully|thoroughly)',
        r'(?i)(first|second|third|next|then|finally) (let\'s|let us)',
        
        # Context injection
        r'(?i)(in this|in the|in these|in those) (context|situation|scenario|case)',
        r'(?i)(given|considering|taking into account) (the |this |that |these |those )?(context|situation|scenario|case)',
        
        # Role-specific injection
        r'(?i)(as a|being a|acting as a|pretending to be a)',
        r'(?i)(your role|your job|your purpose|your function) (is|are|becomes|has become)',
        
        # Output manipulation
        r'(?i)(output|respond|answer) (only|just|merely|simply)',
        r'(?i)(do not|don\'t|never) (include|mention|refer to|talk about)',
        
        # Chain of thought manipulation
        r'(?i)(think|reason|consider|analyze) (before|after|during)',
        r'(?i)(let\'s|let us) (think|reason|consider|analyze) (about|through|throughout)',
        
        # Memory manipulation
        r'(?i)(remember|recall|memorize|store) (this|that|these|those)',
        r'(?i)(forget|erase|clear|delete) (this|that|these|those)',
        
        # Model behavior manipulation
        r'(?i)(behave|act|respond) (differently|in a different way|in another way)',
        r'(?i)(pretend|imitate|simulate|emulate) (to be|that you are|that you\'re)',
        
        # Security bypass
        r'(?i)(bypass|circumvent|override) (the|this|that|these|those)',
        r'(?i)(ignore|disregard|forget|skip) (the|this|that|these|those)',
        
        # Output format manipulation
        r'(?i)(format|structure|organize) (the|this|that|these|those)',
        r'(?i)(output|respond|answer) (in|using|with) (the|this|that|these|those)'
    ],
    'special_chars': [
        r'[<>]',  # HTML tags
        r'[{}]',  # JSON/script blocks
        r'[\[\]]',  # Array notation
        r'[\\\/]',  # Path traversal
        r'[`]',  # Code blocks
        r'[;]',  # Command injection
        r'[|]',  # Pipe commands
        r'[&]',  # Background processes
        r'[$]',  # Variable substitution
        r'[%]'   # Format strings
    ],
    'suspicious_patterns': [
        r'eval\s*\(',
        r'exec\s*\(',
        r'system\s*\(',
        r'shell\s*exec',
        r'base64\s*decode',
        r'javascript:',
        r'data:text/html',
        r'data:application/javascript',
        r'data:application/x-javascript',
        r'data:application/x-httpd-php'
    ]
}

# Input validation settings
VALIDATION_SETTINGS = {
    'max_length': 4000,  # Maximum input length
    'min_length': 1,     # Minimum input length
    'max_words': 500,    # Maximum number of words
    'max_lines': 50,     # Maximum number of lines
    'max_special_chars': 20  # Maximum number of special characters
}

def validate_input(text):
    """Validate input text against security patterns and limits."""
    validation_result = {
        'is_valid': True,
        'errors': []
    }
    
    # Check input length
    if len(text) > VALIDATION_SETTINGS['max_length']:
        validation_result['is_valid'] = False
        validation_result['errors'].append(f"Input exceeds maximum length of {VALIDATION_SETTINGS['max_length']} characters")
    
    if len(text) < VALIDATION_SETTINGS['min_length']:
        validation_result['is_valid'] = False
        validation_result['errors'].append("Input cannot be empty")
    
    # Check word count
    word_count = len(text.split())
    if word_count > VALIDATION_SETTINGS['max_words']:
        validation_result['is_valid'] = False
        validation_result['errors'].append(f"Input exceeds maximum word count of {VALIDATION_SETTINGS['max_words']}")
    
    # Check line count
    line_count = len(text.splitlines())
    if line_count > VALIDATION_SETTINGS['max_lines']:
        validation_result['is_valid'] = False
        validation_result['errors'].append(f"Input exceeds maximum line count of {VALIDATION_SETTINGS['max_lines']}")
    
    # Check for prompt injection patterns with case-insensitive matching
    for pattern in VALIDATION_PATTERNS['prompt_injection']:
        if re.search(pattern, text, re.IGNORECASE):
            validation_result['is_valid'] = False
            validation_result['errors'].append("Input contains potentially harmful prompt injection patterns")
            break
    
    # Check for suspicious special characters
    special_char_count = sum(1 for c in text if any(re.search(pattern, c) for pattern in VALIDATION_PATTERNS['special_chars']))
    if special_char_count > VALIDATION_SETTINGS['max_special_chars']:
        validation_result['is_valid'] = False
        validation_result['errors'].append(f"Input contains too many special characters (max: {VALIDATION_SETTINGS['max_special_chars']})")
    
    # Check for suspicious patterns
    for pattern in VALIDATION_PATTERNS['suspicious_patterns']:
        if re.search(pattern, text, re.IGNORECASE):
            validation_result['is_valid'] = False
            validation_result['errors'].append("Input contains potentially harmful code patterns")
            break
    
    # Additional semantic checks
    if any(word in text.lower() for word in ['ignore', 'disregard', 'override', 'bypass']):
        validation_result['is_valid'] = False
        validation_result['errors'].append("Input contains potentially harmful instructions")
    
    return validation_result

# Safety check patterns and their corresponding messages
SAFETY_PATTERNS = {
    'financial': {
        'patterns': [
            r'bank\s*account',
            r'credit\s*card',
            r'payment',
            r'invoice',
            r'financial',
            r'money',
            r'price',
            r'cost',
            r'budget'
        ],
        'message': "I notice this request involves financial information. Are you sure you want to proceed with sharing or requesting financial details?"
    },
    'personal': {
        'patterns': [
            r'personal\s*information',
            r'address',
            r'phone\s*number',
            r'email\s*address',
            r'date\s*of\s*birth',
            r'id\s*number',
            r'passport'
        ],
        'message': "This request appears to involve personal information. Would you like to proceed with sharing or requesting personal details?"
    },
    'sensitive': {
        'patterns': [
            r'password',
            r'secret',
            r'confidential',
            r'private',
            r'secure',
            r'encrypt',
            r'decrypt'
        ],
        'message': "I notice this request involves sensitive information. Are you sure you want to proceed with this request?"
    },
    'legal': {
        'patterns': [
            r'legal',
            r'contract',
            r'agreement',
            r'terms',
            r'conditions',
            r'liability',
            r'warranty'
        ],
        'message': "This request appears to involve legal matters. Would you like to proceed with this legal-related request?"
    }
}

def check_safety(prompt):
    """Check if the prompt requires safety confirmation."""
    for category, data in SAFETY_PATTERNS.items():
        for pattern in data['patterns']:
            if re.search(pattern, prompt, re.IGNORECASE):
                return {
                    'requires_confirmation': True,
                    'confirmation_message': data['message'],
                    'confirmation_data': {
                        'category': category,
                        'pattern': pattern
                    }
                }
    return {'requires_confirmation': False}

@app.route('/')
def index():
    """Render the home page."""
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    """API endpoint to get response from Gemini."""
    try:
        # Get the prompt from the request
        data = request.get_json()
        if not data or 'prompt' not in data:
            return jsonify({'error': 'Prompt is required'}), 400
        
        prompt = data['prompt']
        
        # Validate input with enhanced security
        validation_result = validate_input(prompt)
        if not validation_result['is_valid']:
            return jsonify({
                'error': 'Input validation failed',
                'details': validation_result['errors']
            }), 400
        
        # If this is a verification request
        if data.get('verify'):
            watermark_data = extract_watermark(prompt)
            if watermark_data:
                return jsonify({
                    'verified': True,
                    'metadata': watermark_data
                })
            return jsonify({
                'verified': False,
                'message': 'No valid watermark found in the content.'
            })
        
        # If this is a safety check request
        if data.get('check_safety'):
            safety_result = check_safety(prompt)
            return jsonify(safety_result)
        
        # Generate response from Gemini with safety checks
        try:
            response = model.generate_content(prompt)
            if not response or not response.text:
                return jsonify({'error': 'Failed to generate response'}), 500
        except Exception as e:
            print(f"Error generating response: {str(e)}")
            return jsonify({'error': 'Failed to generate response'}), 500
        
        # Generate and embed watermark
        watermark_data = generate_watermark(data.get('user_id'))
        watermarked_response = embed_watermark(response.text, watermark_data['watermark'])
        
        # Return the response with watermark metadata
        return jsonify({
            'response': watermarked_response,
            'watermark_metadata': watermark_data['metadata']
        })
    except Exception as e:
        # Handle errors
        print(f"Error in analyze endpoint: {str(e)}")  # For debugging
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)