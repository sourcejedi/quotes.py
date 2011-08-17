#!/usr/bin/env python3
# -*- coding: UTF-8

import sys
import os
import glob
import optparse
import io

try:
	import html.entities
except ImportError:
	# PYTHON2
	class html:
		import htmlentitydefs as entities

# TODO list:
#
#  test cases / examples

# NOT IMPLEMENTED:
#  character encoding must be specified manually (if not UTF-8)
#  <q> tags will be ignored
#  <pre> will be treated as one big paragraph
#  <br> - even multiple successive line breaks 
#         will not be treated as a paragraph break

opt = optparse.OptionParser(usage="%prog [operations] [options] [FILES]")

opt.add_option('-m', '--modify',
	action="store_true", dest="modify",
	help="modify original file(s)")

opt.add_option('--encoding',
	dest="encoding", default="UTF-8")


opt_do = optparse.OptionGroup(opt, 'Operations')
opt_do.add_option('-n', '--none',
	action="store_true", dest="no_output",
	help="show statistics only")

opt_do.add_option('-a', '--all',
	action="store_true", dest="do_all")

opt_do.add_option('--apostrophe',
	action="store_true", dest="do_apostrophe",
	help="mark ambiguous quote/apostrophe at end of words")

opt_do.add_option('--mismatch',
	action="store_true", dest="do_mismatch",
	help="check for mismatched quotes and curly brackets")

opt_do.add_option('--spacing',
	action="store_true", dest="do_spacing",
	help="check for quote marks with odd spacing")

opt_do.add_option('--nesting',
	action="store_true", dest="do_nesting",
	help="check nested quotations")
opt.add_option_group(opt_do)


opt_conf = optparse.OptionGroup(opt, 'General options')
opt_conf.add_option('--ignore-straight-quotes',
	action="store_true", dest="ignore_straight_quotes",
	help="don't try to convert 'straight' quotation marks "
		"(this implies they will not be checked at all)")

opt_conf.add_option('--warning-mark',
	dest="WARN", default='#', metavar="MARK",
	help='warning marker used by most operations, default is "%default"')
opt.add_option_group(opt_conf)


opt_conf = optparse.OptionGroup(opt, 'Options for --apostrophe')
opt_conf.add_option('--skip-leading-apostrophes',
	action="store_true", dest="skip_leading_apostrophe",
	help="don't mark apostrophes at the start of words")

opt_conf.add_option('--mark', dest="MARK", default='*',
	help='marker for ambiguous apostrophes, default is "%default"')
opt.add_option_group(opt_conf)


opt_conf = optparse.OptionGroup(opt, 'Options for --nesting')
opt_conf.add_option('--allow-same-quotes',
	action="store_true", dest="allow_same_quotes",
	help="allow nested quotations which use "
		"the same style of quotation marks")

opt_conf.add_option('--max-depth',
	type="int", dest="max_depth", metavar="N", default=2,
	help="maximum depth of nested quotations/brackets, "
		"default value is %default")
opt.add_option_group(opt_conf)


# Now parse arguments
(options, args) = opt.parse_args()

ops = [option for option in options.__dict__ if option.startswith('do_')]

do_ops = [op for op in ops if getattr(options, op)]
if do_ops:
	if options.no_output:
		print("-n / --none doesn't make sense with any other operation")
		sys.exit(1)
else:
	if options.modify:
		# --modify defaults to --all
		options.do_all = True
	else:
		# otherwise default to --none
		options.do_none = True

if options.do_all:
	# --all enables every operation
	for op in ops:
		setattr(options, op, True)


# Ambiguities and warnings are marked
# with these characters in our output.
OUTPUT_MARK = options.MARK # "*"
OUTPUT_WARN = options.WARN # "#"


class Counters:
	def __init__(count):
		count.openq = 0
		count.closeq = 0

		count.leading_apostrophe = 0
		count.ambiguous_apostrophe = 0

		count.unmatched_q = 0
		count.unmatched = 0

		count.samequotes = 0
		count.too_deep = 0

		count.spaced_q = 0
		count.unspaced_q = 0

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
# Table cells and list items are also included.
#
PARAGRAPH_ELEMENTS = [
	'p',
	
	'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
	'blockquote',
	'hr',

	# Table cells, table heading cells, list items
	'td', 'th', 'li'

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


class XhtmlTokenizer:
	"""Gonzo xhtml tokenizer.
	
	Callbacks based on expat, except no attribute info,
	and text is delivered one character at a time.
	"""
	
	__slots__ = (
		# The XML token which is currently being read
		# from the input file.  It's safe for the
		# callbacks to clobber this, if they want.
		'xml_token',
	)
	
	def start_element(self, name):
		pass
	def end_element(self, name):
		pass
	def character_data(self, c):
		assert len(c) == 1
	def noncharacter_data(self):
		pass
	def end_file(self):
		pass
	
	def run(self, infile):
		self.xml_token = ''

		def read_char(count=1):
			c = infile.read(count)
			if not c:
				raise StopIteration()
			self.xml_token += c
			return c

		def read_tag(first_c):
			c = first_c
			
			end_tag = False
			if c == '/':
				end_tag = True
				c = read_char()				
			
			name = ''
			while c.isalnum() or c == ':':
				name += c
				c = read_char()
			assert name
			
			while c != '>':
				c = read_char()
			
			if end_tag:
				self.end_element(name)
			elif self.xml_token[-2] == '/':
				self.empty_element(name)
			else:
				self.start_element(name)

		def read_noncharacter_data(end):
			while not self.xml_token.endswith(end):
				read_char()
			self.noncharacter_data()

		def read_cdata():
			def feed(c):
				self.xml_token = c
				self.character_data(c)
			
			c = read_char()
			while True:
				while c != ']':
					self.character_data(c)
					self.xml_token = ''
					c = read_char()
				
				c = read_char()
				if c != ']':
					feed(']')
					feed(c)
					continue
				
				c = read_char()
				if c != '>':
					feed(']')
					feed(']')
					feed(c)
				
				self.xml_token = ']]>'
				self.noncharacter_data()
				return

		def start_token(token):
			assert token.startswith(self.xml_token)
			read_char(len(token) - len(self.xml_token))
			assert token == self.xml_token

		c = read_char()
		while c:
			if c == '<':
				c = read_char()
				
				if c == '!':
					c = read_char()
					if c == '-':
						c = read_char()
						assert c == '-'
						read_noncharacter_data('-->')
					elif c == '[':
						start_token('<![CDATA[')
						self.noncharacter_data()
						self.xml_token = ''
						
						read_cdata()
					else:
						start_token('<!DOCTYPE')
						read_noncharacter_data('>')
				elif c == '?':
					read_noncharacter_data('?>')
				else:
					read_tag(c)
			elif c == '&':
				while c != ';':
					c = read_char()
				
				if self.xml_token[1] == '#':	
					if self.xml_token[2].lower() == 'x':
						c = int(self.xml_token[3:-1], 0x10)
					else:
						c = int(self.xml_token[2:-1])
					self.character_data(chr(c))
				else:
					name = self.xml_token[1:-1]
					c = html.entities.entitydefs[name]
					self.character_data(c)
			else:
				self.character_data(c)
			
			c = self.xml_token = infile.read(1)


def isbreakspace(c):
	# NBSP and thin NBSP
	# (Yes, Unicode defines more types of spaces,
	#  but apparently these are the only ones
	#  which need non-breaking variants.
	#  Brillant!)
	nobreaks = '\u00A0\u202F'
	return c.isspace() and c not in nobreaks


class TextChecker(XhtmlTokenizer):
	__slots__ = ()
	
	__slots__ += ('outfile', 'buf')
	def outfile_init(self, outfile):
		self.outfile = outfile
		
		# Output buffer.  Any number of non-text XML tokens.
		# Before this is written to the output file, we may
		# insert some sort of marker.
		self.buf = []
	
	def save_token(self):
		self.buf.append(self.xml_token)

	def flush_tokens(self):
		o = self.outfile
		for token in self.buf:
			o.write(token)
		o.write(self.xml_token)
		del self.buf[:]

	def output_mark(self, mark):
		# Write a marker to the file,
		# before any buffered output
		self.outfile.write(mark)

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

	__slots__ += ('stack',)
	def punctuation_init(self):
		self.stack = []

	def punctuation_push(self, pq):
		(p, q) = pq
		if self.stack and self.stack[-1].p == p:
			self.stack[-1].count += 1
		else:
			self.stack.append(TextChecker.StackFrame(p, q))
		
		samecount = self.stack[-1].count - self.stack[-1].maybe_popped
		if samecount > 1:
			if options.do_nesting and not options.allow_same_quotes:
				self.output_mark(OUTPUT_WARN)
			counters.samequotes += 1
	
		d = sum([s.count - s.maybe_popped for s in self.stack])
		if options.do_nesting and d > options.max_depth:
			counters.too_deep += 1
			self.output_mark(OUTPUT_WARN + '[' + str(d) + ']')

	def punctuation_pop(self, q):
		if not self.stack:
			if q == "’":
				counters.unmatched_q += 1
			else:
				counters.unmatched += 1
			
			self.output_mark(OUTPUT_WARN)
			return
		
		if q != self.stack[-1].q:
			if len(self.stack) >= 2 and q == self.stack[-2].q and \
			   self.stack[-1].maybe_popped == self.stack[-1].count:
				# Looks like the apostrophes we noted may have been close-quotes
				if options.do_apostrophe:
					self.output_mark(' ' + OUTPUT_MARK * self.stack[-1].maybe_popped)
				self.stack.pop()
				# Fall through to pop p as well
			else:
				self.output_mark(OUTPUT_WARN + '[' + self.stack[-1].p + '] ')
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
		if options.do_apostrophe:
			self.output_mark(OUTPUT_MARK)
		
		if self.stack and self.stack[-1].q == q:
			if self.stack[-1].maybe_popped < self.stack[-1].count:
				self.stack[-1].maybe_popped += 1

	def punctuation_endpara(self):
		if self.stack and self.stack[-1].maybe_popped > 0:
			# Looks like some of the apostrophes we noted might have been close-quotes
			if options.do_apostrophe:
				self.output_mark(' ' + OUTPUT_MARK * self.stack[-1].maybe_popped)
			self.stack[-1].count -= self.stack[-1].maybe_popped
			if self.stack[-1].count <= 0:
				self.stack.pop()

		if self.stack:
			self.output_mark(' ' + OUTPUT_WARN + '[')
			for frame in self.stack:
				self.output_mark(frame.p)
				
				# This may cause some errors to be counted twice
				if frame.p == "‘":
					counters.unmatched_q += 1
				else:
					counters.unmatched += 1
			self.output_mark(']')
			self.stack = []
	
	__slots__ += ('history', 'hidden_element')
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

		if not options.ignore_straight_quotes:
			if next == "'":
				counters.straight_q += 1
				if isbreakspace(cur):
					# Could be open-quote OR leading apostrophe.
					# We assume open-quote.
					# If we get it wrong, it should get flagged as a quote mismatch error
					#  - unless there is an ambiguous trailing apostrophe - which is what
					# the ambiguity markers are there for.
					next = "‘"
				else:
					next = "’"
				self.xml_token = next
				
			elif next == '"':
				counters.straight_q2 += 1
				if isbreakspace(cur):
					next = '“'
				else:
					next = '”'
				self.xml_token = next

			# Done rewriting; update history
			del self.history[0]
			self.history.append(next)
		
		# NOTIMPL: Could do nospace here too
		# TODO: make optional?
		if cur == '(':
			self.punctuation_push('()')
		elif cur == ')':
			self.punctuation_pop(')')

		elif cur == '“':
			if prev.isalnum():
				counters.unspaced_q += 1
				if options.do_spacing:
					self.output_mark(OUTPUT_WARN)
			if isbreakspace(next):
				counters.spaced_q += 1
				if options.do_spacing:
					self.output_mark(OUTPUT_WARN)
			self.punctuation_push('“”')
		elif cur == '”':
			if isbreakspace(prev):
				counters.spaced_q += 1
				if options.do_spacing:
					self.output_mark(OUTPUT_WARN)
			if next.isalnum():
				counters.unspaced_q += 1
				if options.do_spacing:
					self.output_mark(OUTPUT_WARN)
			self.punctuation_pop('”')

		# Open quote
		elif cur == "‘":
			counters.openq += 1
			if prev.isalnum():
				counters.unspaced_q += 1
				if options.do_spacing:
					self.output_mark(OUTPUT_WARN)
			if isbreakspace(next):
				counters.spaced_q += 1
				if options.do_spacing:
					self.output_mark(OUTPUT_WARN)
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
					if options.do_apostrophe and \
					   not options.skip_leading_apostrophe:
						self.output_mark(OUTPUT_MARK)
				else:
					if isbreakspace(prev):
						counters.spaced_q += 1
						if options.do_spacing:				
							self.output_mark(OUTPUT_WARN)
					# Not attached to word - must be a closing quote
					counters.closeq += 1
					self.punctuation_pop("’")

	def character_data(self, c):	
		if not self.hidden_element:
			# All whitespace characters are treated the same
			# (apart from NBSP)
			if isbreakspace(c):
				c = ' '
			self.__character(c)
		self.flush_tokens()

	def __paragraph_break(self):
		self.__character('\n')
		self.punctuation_endpara()

	def start_element(self, name, *_):
		if name in INVISIBLE_ELEMENTS:
			self.hidden_element.append(name)
		if name in PARAGRAPH_ELEMENTS:
			self.__paragraph_break()
		self.save_token()

	def end_element(self, name):
		if name in INVISIBLE_ELEMENTS:
			self.hidden_element.pop()
		if name in PARAGRAPH_ELEMENTS:
			self.__paragraph_break()
		self.save_token()

	def empty_element(self, name):
		if name in PARAGRAPH_ELEMENTS:
			self.__paragraph_break()
		self.save_token()
	
	def noncharacter_data(self):
		self.save_token()

	def end_file(self):
		self.flush_tokens()


infile = sys.stdin
outfile = sys.stdout

# PYTHON2: fallback for unicode stdin/stdout (much slower)
if hasattr(infile.read(0), 'decode'):
	import codecs
	infile = codecs.getreader(options.encoding)(infile)
	outfile = codecs.getwriter(options.encoding)(outfile)

if options.no_output:
	class NullWriter:
		def write(self, d):
			pass
		def close(self):
			pass
	outfile = NullWriter()

if not args:
	if options.modify:
		print("--modify requires at least one filename")
		sys.exit(1)
	
	TextChecker(outfile).run(infile)
	infile.close()
	outfile.close()
else:
	if os.name != 'posix':
		filenames = []
		for filename in args:
			filenames += glob.glob(filename)
		args = filenames

	for filename in args:
		infile = io.open(filename, 'r', encoding=options.encoding, newline='\n')
		if options.modify:
			outfile = io.open(filename+".tmp", 'w', encoding=options.encoding, newline='\n')
		
		TextChecker(outfile).run(infile)
		
		if options.modify:
			os.rename(filename+".tmp", filename)
		
		infile.close()
		outfile.close()


report = sys.stderr
report.write("\nSingle quotes")
report.write("\n                    open quotes: " + str(counters.openq))
report.write("\n       unambiguous close quotes: " + str(counters.closeq))
report.write("\n")

# remember that curly apostrophes is our USP.

# do only +mismatches (apostrophe samequotes)
# - limit to apostrophe mismatches only

report.write("\nApostrophes")
report.write("\n    apostrophe at start of word: " + str(counters.leading_apostrophe))
report.write("\n    ambiguous close-quote /")
report.write("\n      apostrophe at end of word: " + str(counters.ambiguous_apostrophe))
report.write("\n")

report.write("\nUnmatched quotes and brackets")
report.write("\n   single quotes (conservative): " + str(counters.unmatched_q))
report.write("\n   double quotes and brackets  : " + str(counters.unmatched))
report.write("\n")

#FIXME --nested-quotes --allow-samequotes
report.write("\nNested quotations")
report.write("\n          nested " + str(options.max_depth + 1) +
                                 " deep or more: " + str(counters.too_deep))
report.write("\n      with same style of quotes: " + str(counters.samequotes))
report.write("\n")

# TODO document
#  - check cases with no spaces, which might have been mis-handled
#  - this will also happen to flag up:
#    - extra spaces from OCR, which can often cause quotes to go in the wrong direction
#    - absence of NBSP in adjacent nested quotation marks
#    - absence of NBSP around en dash just inside quotation mark
#    - as above, for spaced out elipsis
#    (and any similar unsual typographic features)
# 

# TODO need to document NBSP specifically, because the distinction is technical and not obvious to the eye

report.write("\nQuote spacing")
report.write("\n              unexpected spaces: " + str(counters.spaced_q))
report.write("\n                 missing spaces: " + str(counters.unspaced_q))
report.write("\n")

# TODO document as defaulting to open-quotes (with user free to search+replace all)
report.write("\nStraight quote characters")
report.write("\n         straight single quotes: " + str(counters.straight_q))
report.write("\n         straight double quotes: " + str(counters.straight_q2))
report.write("\n")

#TODO: progress indication
