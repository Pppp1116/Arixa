# Astra Language Tour

This is a short, runnable tour of core Astra features.

## 1. Basic function and locals

```astra
fn add(a Int, b Int) Int{
  sum = a + b;
  return sum;
}

fn main() Int{
  return add(20, 22);
}
```

## 2. Control flow and range `for`

```astra
fn main() Int{
  mut total = 0;
  for i in 1..=5 {
    total += i;
  }
  return total; // 15
}
```

`for` also works over `Vec<T>`, slices (`&[T]`/`&mut [T]`), and `Bytes`:

```astra
fn main() Int{
  mut v: Vec<Int> = vec_new() as Vec<Int>;
  drop vec_push(v, 4);
  drop vec_push(v, 5);
  mut sum = 0;
  for x in v {
    sum += x;
  }
  return sum; // 9
}
```

## 3. Option values and coalesce

```astra
fn main() Int{
  maybe: Option<Int> = none;
  value = maybe ?? 7;
  return value;
}
```

## 4. Match with wildcard arm

```astra
fn main() Int{
  ok = true;
  match ok {
    true => { return 1; }
    _ => { return 0; }
  }
}
```

## 5. Structs and field access

```astra
struct Point { x Int, y Int }

fn main() Int{
  p = Point(3, 4);
  return p.x + p.y;
}
```

## 6. Build and run

```bash
astra build examples/hello.astra -o build/hello.py
python build/hello.py
```

For native output:

```bash
astra build examples/hello.astra -o build/hello --target native
./build/hello
```
