#!/usr/bin/env python3

# Ambiguities and warnings will be marked with an asterix
OUTPUT_MARK = "*"
OUTPUT_ERR = "#"

# TODO
#  character encoding
#
#  at least document how to disable / enable individual checks using comments
#
#  error counters + summary
#  (and ideally, separate listing of all errors, grouped by category)
#
#  test cases

# NOT IMPLEMENTED:
#  lists (undefined behaviour)
#  <q> tags (will simply be ignored)


import sys
infile = sys.stdin
outfile = sys.stdout
#
# Use "expat", the xml tokenizer.
#
# We don't enable namespace handling. We assume the document sets
# the default namespace to the HTML one.
#
import xml.parsers.expat
parser = xml.parsers.expat.ParserCreate()


# Current xml token
echo_buf = ""

# We echo each xml token, verbatim
def echo_flush():
	global echo_buf
	outfile.write(echo_buf)
	echo_buf = ""


# A look-back history of three tokens
history = "\n\n\n"

#
# PARAGRAPH_ELEMENTS
#
# A list of the HTML elements which indicate a new paragraph.
# Mostly those which default to CSS display:block.
#
# Derived from HTML5, this is supposed to be all "flow content"
# that is not declared as "phrasing content"
# (which would default to display:inline).
#
# Table cells are also included.
#
# NOT IMPLEMENTED: The behaviour of list items is not defined.
#
PARAGRAPH_ELEMENTS = [
	'p',
	
	'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
	'blockquote',
	'hr',

	# Table cells (and table heading cells)
	'td', 'th',

	'html',
	'title',
	'body',
	'div',
	# <center> was an alias for <div align="center"> 
	'center',
	
	# HTML5
	'section', 'article',
	'aside',
	
	# At least force paragraph breaks around <pre>,
	# even if we don't handle the contents correctly.
	'pre',
]

#
# INVISIBLE_ELEMENTS
#
# List of elements whose content will not be displayed.
# (display:none)
#
INVISIBLE_ELEMENTS = ['script', 'style']
hidden_stack = []


# Stack to keep track of the closing punctation marks we expect to see.
punctuation_stack = []



def punctuation_pop(p):
	if not punctuation_stack:
		outfile.write(OUTPUT_ERR)
		return
	
	if punctuation_stack[-1] != p:
		outfile.write(OUTPUT_ERR)
		return
	
	punctuation_stack.pop()


def __character(c):
	# Checks at this point will output a mark _before_ the current character
	
	history_s = history + c
	if history_s.endswith("‘ "):
		outfile.write(OUTPUT_MARK)
	if history_s.endswith(" ’ "):
		outfile.write(OUTPUT_MARK)

	if history_s[-2] in ["'", '"']:
		outfile.write(OUTPUT_MARK)

	if history_s[-2] == '(':
		punctuation_stack.append(')')
	if history_s[-2] == ')':
		punctuation_pop(')')

	if history_s[-2] == '[':
		punctuation_stack.append(']')
	if history_s[-2] == ']':
		punctuation_pop(']')	

	if history_s[-2] == "’":
		if not history_s[-3].isalpha():
			if not history_s[-1].isalpha():
				# Not attached to word - must be a closing quote
				punctuation_pop('1')
			else:
				# Should be a start-of-word apostrophe - but there's a possibility it's a wrongly-angled opening quote, and there's usually not too many of these to check.
				outfile.write(OUTPUT_MARK)
		else:
			if not history_s[-1].isalpha():
				# Ambiguous - could be end-of-word apostrophe OR closing quote
				outfile.write(OUTPUT_MARK)
			else:
				# Internal, must be apostrophe
				pass
		
	# Open quote
	if history_s[-2] == '‘':
		#TODO nospace
		punctuation_stack.append('1')


def character_data(c):
	global history
	assert len(c) == 1
	
	if c.isspace():
		# All ASCII whitespace characters are treated the same
		c = ' '
	
	if not hidden_stack:
		# Collapse whitespace characters in runs and at start of paragraphs
		if not (c == ' ' and (history[-1] == ' ' or history[-1] == '\n')):
			__character(c)

	echo_flush()
	
	history = history[1:] + c

def __paragraph_break():
	global history
	global punctuation_stack
	
	__character('\n')
	
	if punctuation_stack:
		outfile.write(' ' + OUTPUT_MARK * len(punctuation_stack))
		punctuation_stack = []
	
	history = history[1:] + '\n'


def start_element(name, attrs):
	if name in INVISIBLE_ELEMENTS:
		hidden_stack.append(name)
	if name in PARAGRAPH_ELEMENTS:
		__paragraph_break()

def end_element(name):
	if name in INVISIBLE_ELEMENTS:
		hidden_stack.pop()
	if name in PARAGRAPH_ELEMENTS:
		__paragraph_break()

parser.StartElementHandler = start_element
parser.EndElementHandler = end_element
parser.CharacterDataHandler = character_data

# Optimisation note: one character at a time is probably quite inefficient.  We could probably feed multiple characters and use parser.CurrentByteIndex to keep echo'd ouput in sync with our extra/modified output.
c = infile.read(1)
while c:
	echo_buf += c
	parser.Parse(c)
	c = infile.read(1)

# Tell parser we've reached the end of the file
parser.Parse('', True)
echo_flush()
