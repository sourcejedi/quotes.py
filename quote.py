#!/usr/bin/env python3
# -*- coding: UTF-8

import sys
import xml.parsers.expat


# Ambiguities and warnings will be marked with an asterix
OUTPUT_MARK = "*"
OUTPUT_ERR = "#"

mark_ambiguous_apostrophe =	1
mark_leading_apostrophe = 	1


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


class Counters:
	def __init__(count):
		count.openq = 0
		count.closeq = 0

		count.leading_apostrophe = 0
		count.ambiguous_apostrophe = 0

		count.unmatched_q = 0
		count.unmatched = 0

		count.misspaced_q = 0

		count.straight_q = 0
		count.straight_q2 = 0
counters = Counters()


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
# List of elements whose content would not be displayed.
# (display:none)
#
INVISIBLE_ELEMENTS = ['script', 'style']


class TextChecker:
	# Output buffer
	def outfile_init(self, outfile):
		self.outfile = outfile
		
		# The single XML token which is currently being read
		# from the input file.  May be modified in-place.
		self.token = ""
		
		# Writeout buffer.  Any number of non-text XML tokens.
		# Before this is written to the output file, we may
		# insert some sort of marker.
		self.buf = ""
	
	def token_add_char(self, c):
		self.token += c
	
	def token_rewrite(self, token):
		self.token = token
	
	def token_end(self):
		self.buf += self.token
		self.token = ""

	def output_mark(self, mark):
		# Write a marker to the file,
		# before any buffered output
		self.outfile.write(mark)

	def flush_tokens(self):
		self.outfile.write(self.buf)
		self.outfile.write(self.token)
		self.buf = self.token = ""


	# Stack to keep track of the current "open" punctuation marks,
	# with a _limited_ non-deterministic pop() used to handle
	# apostrophes which might be close-quote characters
	class StackFrame:
		__slots__ = ('p', 'q', 'count', 'maybe_popped')
		
		def __init__(self, p, q, count=1, maybe_popped=0):
			self.p = p
			self.q = q
			self.count = count
			self.maybe_popped = maybe_popped
		
		def __repr__(self):
			return 'StackFrame' + \
			repr((self.p, self.count, self.maybe_popped))

	def punctuation_init(self):
		self.stack = []

	def punctuation_push(self, pq):
		(p, q) = pq
		if self.stack and self.stack[-1].p == p:
			self.stack[-1].count += 1
		else:
			self.stack.append(TextChecker.StackFrame(p, q))
	
	def punctuation_pop(self, q):
		if not self.stack:
			self.output_mark(' ' + OUTPUT_ERR + '[' + q + ']')
			return
		
		if q != self.stack[-1].q:
			if len(self.stack) >= 2 and q == self.stack[-2].q and \
			self.stack[-1].maybe_popped == self.stack[-1].count:
				# Looks like the apostrophes we noted may have been close-quotes
				if mark_ambiguous_apostrophe:
					self.output_mark(' ' + OUTPUT_MARK * self.stack[-1].maybe_popped)
				self.stack.pop()
				# Fall through to pop p as well
			else:
				self.output_mark(' ' + OUTPUT_ERR + '[' + self.stack[-1].p + ']')
				# No attempt at recovery here. We may
				# generate some confusing-looking errors
				# until we get to the next paragraph,
				# though they're still pretty easy to
				# understand if you know what we're doing.
				if q == "’" or self.stack[-1].p == "‘":
					counters.unmatched_q += 1
				else:
					counters.unmatched += 1
				return
		
		self.stack[-1].count -= 1
		if self.stack[-1].maybe_popped > self.stack[-1].count:
			self.stack[-1].maybe_popped = self.stack[-1].count
		if self.stack[-1].count <= 0:
			self.stack.pop()

	def punctuation_maybe_pop(self, q):
		if mark_ambiguous_apostrophe:
			self.output_mark(OUTPUT_MARK)
		
		if self.stack and self.stack[-1].q == q:
			if self.stack[-1].maybe_popped < self.stack[-1].count:
				self.stack[-1].maybe_popped += 1

	def punctuation_endpara(self):
		if self.stack and self.stack[-1].maybe_popped > 0:
			# Looks like some of the apostrophes we noted might have been close-quotes
			if mark_ambiguous_apostrophe:
				self.output_mark(' ' + OUTPUT_MARK * self.stack[-1].maybe_popped)
			self.stack[-1].count -= self.stack[-1].maybe_popped
			if self.stack[-1].count <= 0:
				self.stack.pop()
		
		if self.stack:
			self.output_mark(' ' + OUTPUT_ERR + '[')
			for frame in self.stack:
				self.output_mark(frame.p)
				if frame.p == "‘":
					counters.unmatched_q += 1
				else:
					counters.unmatched += 1
			self.output_mark(']')
			self.stack = []
	
	
	def __init__(self, outfile):
		self.outfile_init(outfile)
		self.punctuation_init()

		# An input window of three "characters".
		# These are non-space characters from text nodes,
		# " " for a run of whitespace characters, or
		# "\n" for a paragraph break.
		#
		# We can insert a marker after the middle character
		# using output_mark()
		self.history = ["\n", "\n", "\n"]

		self.hidden_element = []


	def __character(self, next):
		# At this point, "token" contains the representation of
		# the character "c", and may be modified;
		# output marks will appear just _before_ the character "c"

		(prev, cur) = (self.history[-2], self.history[-1])

		# Convert straight quotes (TODO: option)
		if next == "'":
			counters.straight_q += 1
			if cur.isspace():
				# Could be open-quote OR leading apostrophe.
				# We assume open-quote.
				# If we get it wrong, it should get flagged as a quote mismatch error
				#  - unless there is an ambiguous trailing apostrophe - which is what
				# the ambiguity markers are there for.
				next = "‘"
			else:
				next = "’"
			self.token_rewrite(next)
			
		elif next == '"':
			counters.straight_q2 += 1
			if cur.isspace():
				next = '“'
			else:
				next = '”'
			self.token_rewrite(next)
		
		# Done rewriting; update history
		del self.history[0]
		self.history.append(next)
		
		# NOTIMPL: Could do nospace here too
		# TODO: make optional
		if cur == '(':
			self.punctuation_push('()')
		elif cur == ')':
			self.punctuation_pop(')')

		elif cur == '“':
			# TODO: count, suppress (missing NBSP)
			if prev.isalnum() or next.isspace():
				counters.misspaced_q += 1
				self.output_mark(OUTPUT_ERR)
			self.punctuation_push('“”')
		elif cur == '”':
			if prev.isspace() or next.isalnum():
				self.output_mark(OUTPUT_ERR)
			self.punctuation_pop('”')

		# Open quote
		elif cur == "‘":
			counters.openq += 1
			if prev.isalnum() or next.isspace():
				counters.misspaced_q += 1
				self.output_mark(OUTPUT_ERR)
			self.punctuation_push("‘’")

		elif cur == "’":
			if prev.isalpha():
				if next.isalpha():
					# Internal, must be apostrophe
					pass
				else:
					# Ambiguous - could be end-of-word apostrophe OR closing quote
					counters.ambiguous_apostrophe += 1
					self.punctuation_maybe_pop("’")
			else:
				if next.isalnum():
					# Should be a start-of-word apostrophe - but there's a possibility it's a wrongly-angled opening quote, and there's usually not too many of these to check.
					# (FIXME could use a flag of it's own though)
					counters.leading_apostrophe += 1
					if mark_leading_apostrophe:
						self.output_mark(OUTPUT_MARK)
				else:
					if prev.isspace():
						self.output_mark(OUTPUT_ERR)
					# Not attached to word - must be a closing quote
					counters.closeq += 1
					self.punctuation_pop("’")

	def character_data(self, c):	
		#FIXME FIXME FIXME CDATA breaks this.
		# back to the regexs
	
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

		if self.hidden_element:
			return
			
		if c.isspace():
			# All whitespace characters are treated the same
			c = ' '
					
		if c == ' ' and self.history[-1].isspace():
			return

		self.__character(c)
		self.flush_tokens()

	def __paragraph_break(self):
		self.__character('\n')
		self.punctuation_endpara()

	def start_element(self, name, attrs):
		if name in INVISIBLE_ELEMENTS:
			self.hidden_element.append(name)
		if name in PARAGRAPH_ELEMENTS:
			self.__paragraph_break()
		self.token_end()

	def end_element(self, name):
		if name in INVISIBLE_ELEMENTS:
			self.hidden_element.pop()
		if name in PARAGRAPH_ELEMENTS:
			self.__paragraph_break()		
		self.token_end()

	def noncharacter_data(self, d):
		assert d == self.token
		self.token_end()

	def run(self, infile):
		# We don't enable namespace handling.
		# We assume the document sets
		# the default namespace to the HTML one,
		# as required by the XHTML DTDs.
		parser = xml.parsers.expat.ParserCreate()

		parser.StartElementHandler = self.start_element
		parser.EndElementHandler = self.end_element
		parser.CharacterDataHandler = self.character_data
		parser.DefaultHandler = self.noncharacter_data

		# Feed one character at a time.  Probably very inefficient.  But we want to keep echo'd ouput in sync with our extra/modified output.
		c = infile.read(1)
		while c:
			self.token_add_char(c)
			parser.Parse(c)
			c = infile.read(1)

		# Tell parser we've reached the end of the file
		parser.Parse('', True)
		self.flush_tokens()


# NOT IMPLEMENTED: non-UTF-8 encodings
if len(sys.argv) >= 2:
	infile = open(sys.argv[1], 'r')
else:
	infile = sys.stdin
outfile = sys.stdout


t = TextChecker(outfile)
t.run(infile)


# FIXME this will suck for multiple chapter files
# we need to accept multiple files (and glob on windows, i.e. os.name != 'posix')
# and implement some sort of in-place or batch modification

report = sys.stderr
report.write("\nSingle quotes")
report.write("\n                 open quotes: " + str(counters.openq))
report.write("\n    unambiguous close quotes: " + str(counters.closeq))
report.write("\n")
report.write("\nApostrophes")
report.write("\n    apostrophe at start of word: " + str(counters.leading_apostrophe))
report.write("\n      ambiguous close-quote /")
report.write("\n      apostrophe at end of word: " + str(counters.ambiguous_apostrophe))
report.write("\n")
report.write("\nUnmatched quotes and brackets")
report.write("\n    single quotes (conservative): " + str(counters.unmatched_q))
report.write("\n    double quotes and brackets  : " + str(counters.unmatched))
report.write("\n")
report.write("\nExtra or missing spaces around quotes: " + str(counters.misspaced_q))
report.write("\n")
report.write("\nStraight quote characters")

#TODO
#" (not included above)"
#" (converted)"

report.write("\n    single quotes: " + str(counters.straight_q))
report.write("\n    double quotes: " + str(counters.straight_q2))
report.write("\n")
