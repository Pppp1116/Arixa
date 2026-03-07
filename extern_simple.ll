; ModuleID = '<string>'
source_filename = "<string>"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-unknown-linux-gnu"

declare signext i8 @simple_func()

define i64 @__astra_user_main() {
entry:
  %ret = alloca i64, align 8
  store i64 0, ptr %ret, align 8
  %.3 = call i8 @simple_func()
  %result = alloca i8, align 1
  store i8 %.3, ptr %result, align 1
  %.5 = load i8, ptr %result, align 1
  %.6 = sext i8 %.5 to i64
  store i64 %.6, ptr %ret, align 8
  br label %epilogue

epilogue:                                         ; preds = %entry
  %.9 = load i64, ptr %ret, align 8
  ret i64 %.9
}

define i32 @main() {
entry:
  %.2 = call i64 @__astra_user_main()
  %.3 = trunc i64 %.2 to i32
  ret i32 %.3
}
