# ISYCODE over a night valley — authored with GlyphFuck, no runtime dependency.
canvas 76 18 fill " "

glyph I 3 5
  line 0 0 2 0 "#"
  line 1 0 1 4 "#"
  line 0 4 2 4 "#"
end

glyph S 5 5
  line 0 0 4 0 "#"
  line 0 0 0 2 "#"
  line 0 2 4 2 "#"
  line 4 2 4 4 "#"
  line 0 4 4 4 "#"
end

glyph Y 5 5
  line 0 0 2 2 "#"
  line 4 0 2 2 "#"
  line 2 2 2 4 "#"
end

glyph C 5 5
  line 1 0 4 0 "#"
  line 0 1 0 3 "#"
  line 1 4 4 4 "#"
end

glyph O 5 5
  box 0 0 5 5 "#"
end

glyph D 5 5
  line 0 0 0 4 "#"
  line 0 0 3 0 "#"
  line 4 1 4 3 "#"
  line 0 4 3 4 "#"
end

glyph E 5 5
  line 0 0 0 4 "#"
  line 0 0 4 0 "#"
  line 0 2 3 2 "#"
  line 0 4 4 4 "#"
end

# Stars and distant ridge.
point 7 1 "."
point 21 2 "+"
point 34 0 "."
point 47 2 "*"
point 68 1 "."
point 59 3 "+"
point 12 4 "."
point 72 5 "*"
text " .--. " at 35 2
text "(    )" at 35 3
text " '--' " at 35 4
line 0 9 10 4 "/"
line 10 4 19 9 "\\"
line 56 9 65 3 "/"
line 65 3 75 9 "\\"
line 0 11 9 7 "/"
line 9 7 15 10 "\\"
line 61 10 70 6 "/"
line 70 6 75 9 "\\"
point 8 10 "^"
line 5 12 8 10 "/"
line 8 10 11 12 "\\"
line 8 12 8 14 "|"
point 68 10 "^"
line 65 12 68 10 "/"
line 68 10 71 12 "\\"
line 68 12 68 14 "|"

# The wordmark is the center of the valley.
text "ISYCODE" at 38 9 anchor center spacing 1

# Foreground / reflected horizon.
line 0 14 75 14 "_"
line 3 16 21 16 "~"
line 27 16 49 16 "~"
line 55 16 72 16 "~"
point 11 15 "."
point 36 15 "."
point 64 15 "."

expect width 76
expect height 18
expect text "ISYCODE"
expect glyphs_distinct I S Y
render
