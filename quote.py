#!/usr/bin/env python3

# Ambiguities and warnings will be marked with an asterix
OUTPUT_MARK = "*"
OUTPUT_ERR = "#"

mark_ambiguous_apostrophe =	1
mark_leading_apostrophe = 	1


class counters:
	pass
counters = counters()

counters.openq = 0
counters.closeq = 0

counters.leading_apostrophe = 0
counters.ambiguous_apostrophe = 0

counters.unmatched_q = 0
counters.unmatched = 0


# TODO list:
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

#TODO automatic up-conversion of straight quotes

#TODO test and define behaviour of NBSP

#FIXME we're probably not handling named character references

import sys

# NOT IMPLEMENTED: non-UTF-8 encodings
if len(sys.argv) >= 2:
	infile = open(sys.argv[1], 'r')
else:
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


# A look-back history of three tokens.
# Tokens are literal characters from text nodes,
# " " for runs of whitespace characters, and
# "\n" for paragraph breaks.
history = ["\n", "\n", "\n"]



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


# Stack to keep track of the current "open" punctuation marks,
# with a _limited_ non-deterministic pop() used to handle
# apostrophes which might be close-quote characters
stack = []

import collections
class StackFrame(object):
	__slots__ = ('p', 'q', 'count', 'maybe_popped')
	
	def __init__(self, p, q, count=1, maybe_popped=0):
		self.p = p
		self.q = q
		self.count = count
		self.maybe_popped = maybe_popped
	
	def __repr__(self):
		return 'StackFrame' + \
		    repr((self.p, self.count, self.maybe_popped))

def punctuation_push(pq):
	global stack
	
	(p, q) = pq
	if stack and stack[-1].p == p:
		stack[-1].count += 1
	else:
		stack.append(StackFrame(p, q))
	
def punctuation_pop(q):
	global stack
	
	if not stack:
		outfile.write(' ' + OUTPUT_ERR + '[' + q + ']')
		return
	
	if q != stack[-1].q:
		if len(stack) >= 2 and q == stack[-2].q and \
		    stack[-1].maybe_popped == stack[-1].count:
			# Looks like the apostrophes we noted may have been close-quotes
			if mark_ambiguous_apostrophe:
				outfile.write(' ' + OUTPUT_MARK * stack[-1].maybe_popped)
			stack.pop()
			# Fall through to pop p as well
		else:
			outfile.write(' ' + OUTPUT_ERR + '[' + stack[-1].p + ']')
			# No attempt at recovery here. We may
			# generate some confusing-looking errors
			# until we get to the next paragraph,
			# though they're still pretty easy to
			# understand if you know what we're doing.
			if q == "’" or stack[-1].p == "‘":
				counters.unmatched_q += 1
			else:
				counters.unmatched += 1
			return
	
	stack[-1].count -= 1
	if stack[-1].maybe_popped > stack[-1].count:
		stack[-1].maybe_popped = stack[-1].count
	if stack[-1].count <= 0:
		stack.pop()

def punctuation_maybe_pop(q):
	global stack

	if mark_ambiguous_apostrophe:
		outfile.write(OUTPUT_MARK)
	
	if stack and stack[-1].q == q:
		if stack[-1].maybe_popped < stack[-1].count:
			stack[-1].maybe_popped += 1

def punctuation_endpara():
	global stack
	
	if stack and stack[-1].maybe_popped > 0:
		# Looks like some of the apostrophes we noted might have been close-quotes
		if mark_ambiguous_apostrophe:
			outfile.write(' ' + OUTPUT_MARK * stack[-1].maybe_popped)
		stack[-1].count -= stack[-1].maybe_popped
		if stack[-1].count <= 0:
			stack.pop()
	
	if stack:
		outfile.write(' ' + OUTPUT_ERR + '[')
		for s in stack:
			outfile.write(s.p)
			if s.p == "‘":
				counters.unmatched_q += 1
			else:
				counters.unmatched += 1
		outfile.write(']')
		stack = []

def __character(c):
	global buf
	global history
	# At this point, "echo_buf" contains the representation of
	# the character "c", and may be modified;
	# output messages will appear just _before_ the character "c",
	# (so wouldn't it be better to prepend them to c?)
	
	history = history[1:] + [c]
	(prev, cur, next) = history[-3:]

	if next == "'":
		if cur.isspace():
			# Could be open-quote OR leading apostrophe.
			# We assume open-quote.
			# If we get it wrong, it should get flagged as a quote mismatch error
			#  - unless there is an ambiguous trailing apostrophe - which is what
			# the ambiguity markers are there for.
			buf = history[-1] = "‘"
		else:
			buf = history[-1] = "’"
	elif next == '"':
		if cur.isspace():
			buf = history[-1] = '“'
		else:
			buf = history[-1] = '”'
	
	(prev, cur, next) = history[-3:]

	# NOTIMPL: Could do nospace here too
	if cur == '(':
		punctuation_push('()')
	if cur == ')':
		punctuation_pop(')')

	if cur == '“':
		# TODO: count, suppress (missing NBSP)
		if prev.isalnum() or next.isspace():
			outfile.write(OUTPUT_ERR)
		punctuation_push('“”')
	if cur == '”':
		if prev.isspace() or next.isalnum():
			outfile.write(OUTPUT_ERR)
		punctuation_pop('”')

	# Open quote
	if cur == "‘":
		counters.openq += 1
		if prev.isalnum() or next.isspace():
			outfile.write(OUTPUT_ERR)
		punctuation_push("‘’")

	if cur == "’":
		if prev.isalpha():
			if next.isalpha():
				# Internal, must be apostrophe
				pass
			else:
				# Ambiguous - could be end-of-word apostrophe OR closing quote
				counters.ambiguous_apostrophe += 1
				punctuation_maybe_pop("’")
		else:
			if next.isalnum():
				# Should be a start-of-word apostrophe - but there's a possibility it's a wrongly-angled opening quote, and there's usually not too many of these to check.
				# (FIXME could use a flag of it's own though)
				counters.leading_apostrophe += 1
				if mark_leading_apostrophe:
					outfile.write(OUTPUT_MARK)
			else:
				if prev.isspace():
					outfile.write(OUTPUT_ERR)
				# Not attached to word - must be a closing quote
				counters.closeq += 1
				punctuation_pop("’")

# Buffered XML, which will be echoed to outfile
buf = ""
buf_xml = ""

def character_data(c):
	global buf
	global buf_xml
	
	assert len(c) == 1 # FIXME looks like it breaks on ']', presumably because of CDATA escaping.
				# we should probably tolerate it
				# easiest would be to tolerate it with a loop, document it,
				# and expand the assertion.
				#
				# additionally, we could avoid the lack of accuracy by escaping ] 
				# outside of cdata sections
				#
				# of course this is getting hacky, but our concept is already
				# pretty obscene.

	if not hidden_stack:
		if c.isspace():
			# All whitespace characters are treated the same
			c = ' '
		
		if not (c == ' ' and history[-1].isspace()):
			__character(c)

	outfile.write(buf_xml)
	outfile.write(buf)
	buf_xml = ""
	buf = ""

def __paragraph_break():
	__character('\n')
	punctuation_endpara()


def start_element(name, attrs):
	global buf
	global buf_xml
	
	if name in INVISIBLE_ELEMENTS:
		hidden_stack.append(name)
	if name in PARAGRAPH_ELEMENTS:
		__paragraph_break()
	
	buf_xml += buf
	buf = ""

def end_element(name):
	global buf
	global buf_xml
	
	if name in INVISIBLE_ELEMENTS:
		hidden_stack.pop()
	if name in PARAGRAPH_ELEMENTS:
		__paragraph_break()
		
	buf_xml += buf
	buf = ""

def noncharacter_data(d):
	global buf
	global buf_xml
	
	assert d == buf
	buf_xml += buf
	buf = ""

parser.StartElementHandler = start_element
parser.EndElementHandler = end_element
parser.DefaultHandler = noncharacter_data
parser.CharacterDataHandler = character_data

# Feed one character at a time.  Probably very inefficient.  But we want to keep echo'd ouput in sync with our extra/modified output.
c = infile.read(1)
while c:
	buf += c
	parser.Parse(c)
	c = infile.read(1)

# Tell parser we've reached the end of the file
parser.Parse('', True)

outfile.write(buf_xml)
outfile.write(buf)
del buf_xml
del buf

# FIXME this will suck for multiple chapter files
# we need to accept multiple files (and glob on windows, i.e. os.name != 'posix')
# and implement some sort of in-place or batch modification

report = sys.stderr
report.write("COUNTERS")
report.write("\nOpen-single-quote characters (‘): " + str(counters.openq))
report.write("\nUnambiguous single-close-quotes : " + str(counters.closeq))
report.write("\nAmbiguous close-quote /")
report.write("\n  apostrophe at end of word (’) : " + str(counters.ambiguous_apostrophe))
report.write("\nApostrophe at start of word     : " + str(counters.leading_apostrophe))
report.write("\n")
report.write("\nDefinitely unmatched single quotes: " + str(counters.unmatched_q))
report.write("\nOther unmatched characters        : " + str(counters.unmatched))
report.write("\n")
