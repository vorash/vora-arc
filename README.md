# vora-arc

Solves ARC-AGI tasks by having a language model write candidate
`transform(grid)` programs and running each one in a
[Vora](https://github.com/vorash/vora) sandbox. Vora runs the code and reports
raw results; this package decides which programs are correct.

Work in progress: Milestone 1 (harness, no model).
