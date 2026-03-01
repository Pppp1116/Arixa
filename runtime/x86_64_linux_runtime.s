; Astra native runtime for Linux x86-64 (System V ABI).
; Exports runtime ABI symbols used by astra/codegen.py.

default rel

section .rodata
panic_prefix: db "panic: "
panic_prefix_len equ $ - panic_prefix
nl: db 10

section .text
global astra_print_i64
global astra_print_str
global astra_alloc
global astra_free
global astra_panic
global astra_fmod

; void astra_print_i64(i64 value)
astra_print_i64:
  push rbp
  mov rbp, rsp
  sub rsp, 64

  mov rax, rdi
  lea r8, [rbp-1]
  xor r9, r9              ; digit count
  xor r10, r10            ; sign flag
  test rax, rax
  jge .print_loop_check
  mov r10, 1

.print_loop_check:
  cmp rax, 0
  jne .print_loop
  mov byte [r8], '0'
  dec r8
  mov r9, 1
  jmp .print_sign

.print_loop:
  cqo
  mov r11, 10
  idiv r11
  test rdx, rdx
  jge .digit_abs_done
  neg rdx
.digit_abs_done:
  add dl, '0'
  mov byte [r8], dl
  dec r8
  inc r9
  test rax, rax
  jne .print_loop

.print_sign:
  test r10, r10
  jz .print_write
  mov byte [r8], '-'
  dec r8
  inc r9

.print_write:
  lea rsi, [r8+1]
  mov rax, 1              ; sys_write
  mov rdi, 1              ; stdout
  mov rdx, r9
  syscall

  mov rax, 1
  mov rdi, 1
  lea rsi, [rel nl]
  mov rdx, 1
  syscall

  xor rax, rax
  leave
  ret

; void astra_print_str(usize ptr, usize len)
; NOTE: NASM lacks named args, ABI uses rdi=ptr, rsi=len.
astra_print_str:
  push rbp
  mov rbp, rsp

  mov rax, 1              ; sys_write
  mov rdx, rsi            ; len
  mov rsi, rdi            ; ptr
  mov rdi, 1              ; stdout
  syscall

  mov rax, 1
  mov rdi, 1
  lea rsi, [rel nl]
  mov rdx, 1
  syscall

  xor rax, rax
  leave
  ret

; usize astra_alloc(usize size, usize align)
; align is currently ignored; allocator uses page-backed mmap.
astra_alloc:
  push rbp
  mov rbp, rsp

  mov rax, rdi            ; size
  test rax, rax
  jne .alloc_size_ok
  mov rax, 1
.alloc_size_ok:
  mov rsi, rax            ; len
  mov rax, 9              ; sys_mmap
  xor rdi, rdi            ; addr = NULL
  mov rdx, 3              ; PROT_READ | PROT_WRITE
  mov r10, 0x22           ; MAP_PRIVATE | MAP_ANONYMOUS
  mov r8, -1              ; fd = -1
  xor r9, r9              ; offset = 0
  syscall
  leave
  ret

; void astra_free(usize ptr, usize size, usize align)
; align is ignored; size==0 is treated as unknown and becomes a no-op.
astra_free:
  push rbp
  mov rbp, rsp

  test rsi, rsi
  jz .free_done
  mov rax, 11             ; sys_munmap
  ; rdi=ptr, rsi=size already set by ABI.
  syscall
.free_done:
  xor rax, rax
  leave
  ret

; noreturn astra_panic(usize ptr, usize len)
astra_panic:
  push rbp
  mov rbp, rsp

  ; Save panic payload args.
  mov r8, rdi             ; msg ptr
  mov r9, rsi             ; msg len

  ; stderr: "panic: "
  mov rax, 1              ; sys_write
  mov rdi, 2              ; stderr
  lea rsi, [rel panic_prefix]
  mov rdx, panic_prefix_len
  syscall

  ; stderr: user message
  mov rax, 1
  mov rdi, 2
  mov rsi, r8
  mov rdx, r9
  syscall

  ; stderr: newline
  mov rax, 1
  mov rdi, 2
  lea rsi, [rel nl]
  mov rdx, 1
  syscall

  mov rax, 60             ; sys_exit
  mov rdi, 101
  syscall

  ud2

; f64 astra_fmod(f64 x, f64 y)
; SysV: x in xmm0, y in xmm1, return in xmm0.
astra_fmod:
  push rbp
  mov rbp, rsp
  sub rsp, 16

  movsd qword [rsp], xmm0
  movsd qword [rsp+8], xmm1
  fld qword [rsp]       ; st0 = x
  fld qword [rsp+8]     ; st0 = y, st1 = x
  fxch st1              ; st0 = x, st1 = y
.fmod_loop:
  fprem
  fstsw ax
  test ah, 4            ; C2 flag set => iterate
  jnz .fmod_loop
  fstp st1              ; pop divisor
  fstp qword [rsp]      ; pop remainder
  movsd xmm0, qword [rsp]
  leave
  ret
