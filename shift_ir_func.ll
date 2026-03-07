; ModuleID = '<string>'
source_filename = "<string>"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

define i64 @shift_test(i64 %.1, i64 %.2) {
entry:
  %ret = alloca i64, align 8
  store i64 0, ptr %ret, align 8
  %x = alloca i64, align 8
  store i64 %.1, ptr %x, align 8
  %y = alloca i64, align 8
  store i64 %.2, ptr %y, align 8
  %.7 = load i64, ptr %x, align 8
  %.8 = load i64, ptr %y, align 8
  %.9 = icmp sge i64 %.8, 0
  %.10 = icmp slt i64 %.8, 64
  %.11 = and i1 %.9, %.10
  br i1 %.11, label %shift_in_range, label %shift_oob

epilogue:                                         ; preds = %shift_in_range
  %.18 = load i64, ptr %ret, align 8
  ret i64 %.18

shift_in_range:                                   ; preds = %entry
  %.15 = ashr i64 %.7, %.8
  store i64 %.15, ptr %ret, align 8
  br label %epilogue

shift_oob:                                        ; preds = %entry
  call void @llvm.trap()
  unreachable
}

define i64 @__astra_user_main() {
entry:
  %ret = alloca i64, align 8
  store i64 0, ptr %ret, align 8
  %.3 = call i64 @shift_test(i64 -8, i64 1)
  %result = alloca i64, align 8
  store i64 %.3, ptr %result, align 8
  %.5 = load i64, ptr %result, align 8
  store i64 %.5, ptr %ret, align 8
  br label %epilogue

epilogue:                                         ; preds = %entry
  %.8 = load i64, ptr %ret, align 8
  ret i64 %.8
}

; Function Attrs: cold noreturn nounwind memory(inaccessiblemem: write)
declare void @llvm.trap() #0

define i32 @main() {
entry:
  %.2 = call i64 @__astra_user_main()
  %.3 = trunc i64 %.2 to i32
  ret i32 %.3
}

attributes #0 = { cold noreturn nounwind memory(inaccessiblemem: write) }
