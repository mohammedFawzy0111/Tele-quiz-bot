def parse_question(text):
    # Split questions by lines
    lines = text.strip().split('\n')

    question = None
    options = []

    for line in lines:
        # Check if the line contains options
        if ':' in line:
            # Split question and options based on ':'
            question_part, options_part = line.split(':', 1)
            question = question_part.strip()
            # Extracting options which might be inline
            options.extend(opt.strip() for opt in options_part.split(','))
        else:
            # Handle continuation of options or question
            if question is not None:
                # Assuming inline option may appear
                options.append(line.strip())

    # Clean up options by removing duplicates
    options = list(dict.fromkeys(options))
    return question, options

# Example usage
text = '''What is your favorite color? : Red, Blue, Green
Do you like programming? : Yes
Do you enjoy video games? : No, Yes'''

print(parse_question(text)) # Testing the parser
