global _start
section .text
_start:
  push rbp
  mov rbp, rsp
  sub rsp, 16
  mov rax, 0
.L__start_epilogue:
  mov rsp, rbp
  pop rbp
  ret
