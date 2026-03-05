#include <errno.h>
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#if defined(__GNUC__) || defined(__clang__)
typedef __int128 i128;
typedef unsigned __int128 u128;
#else
#error "Astra LLVM runtime requires compiler support for __int128"
#endif

typedef struct AllocNode {
  void *ptr;
  struct AllocNode *next;
} AllocNode;

static AllocNode *g_alloc_head = NULL;
static bool g_alloc_init = false;

static void astra_cleanup_allocs(void) {
  AllocNode *cur = g_alloc_head;
  while (cur != NULL) {
    AllocNode *next = cur->next;
    free(cur->ptr);
    free(cur);
    cur = next;
  }
  g_alloc_head = NULL;
}

static void astra_alloc_init_once(void) {
  if (g_alloc_init) {
    return;
  }
  g_alloc_init = true;
  atexit(astra_cleanup_allocs);
}

static void astra_track_ptr(void *p) {
  if (p == NULL) {
    return;
  }
  astra_alloc_init_once();
  AllocNode *n = (AllocNode *)malloc(sizeof(AllocNode));
  if (n == NULL) {
    return;
  }
  n->ptr = p;
  n->next = g_alloc_head;
  g_alloc_head = n;
}

static void astra_untrack_ptr(void *p) {
  if (p == NULL) {
    return;
  }
  AllocNode *prev = NULL;
  AllocNode *cur = g_alloc_head;
  while (cur != NULL) {
    if (cur->ptr == p) {
      if (prev == NULL) {
        g_alloc_head = cur->next;
      } else {
        prev->next = cur->next;
      }
      free(cur);
      return;
    }
    prev = cur;
    cur = cur->next;
  }
}

static void *astra_heap_alloc(size_t n) {
  size_t want = n == 0 ? 1 : n;
  void *p = malloc(want);
  astra_track_ptr(p);
  return p;
}

static char *astra_strdup_s(const char *s) {
  if (s == NULL) {
    char *out = (char *)astra_heap_alloc(1);
    if (out != NULL) {
      out[0] = '\0';
    }
    return out;
  }
  size_t n = strlen(s);
  char *out = (char *)astra_heap_alloc(n + 1);
  if (out == NULL) {
    return NULL;
  }
  memcpy(out, s, n);
  out[n] = '\0';
  return out;
}

static void astra_trap(void) {
#if defined(__GNUC__) || defined(__clang__)
  __builtin_trap();
#else
  abort();
#endif
}

static i128 astra_i128_min(void) {
  return (i128)(((u128)1) << 127);
}

void astra_print_i64(int64_t value) {
  (void)printf("%lld\n", (long long)value);
  (void)fflush(stdout);
}

void astra_print_str(uintptr_t ptr, uintptr_t len) {
  if (ptr != 0 && len > 0) {
    (void)fwrite((const void *)ptr, 1, (size_t)len, stdout);
  }
  (void)fputc('\n', stdout);
  (void)fflush(stdout);
}

uintptr_t astra_alloc(uintptr_t size, uintptr_t align) {
  size_t n = (size_t)(size == 0 ? 1 : size);
  size_t a = (size_t)(align == 0 ? sizeof(void *) : align);
  if (a < sizeof(void *)) {
    a = sizeof(void *);
  }
  if ((a & (a - 1)) != 0) {
    size_t p2 = sizeof(void *);
    while (p2 < a) {
      p2 <<= 1;
    }
    a = p2;
  }
  void *p = NULL;
  if (posix_memalign(&p, a, n) != 0) {
    return 0;
  }
  astra_track_ptr(p);
  return (uintptr_t)p;
}

void astra_free(uintptr_t ptr, uintptr_t size, uintptr_t align) {
  (void)size;
  (void)align;
  if (ptr != 0) {
    void *p = (void *)ptr;
    astra_untrack_ptr(p);
    free(p);
  }
}

void astra_panic(uintptr_t ptr, uintptr_t len) {
  (void)fprintf(stderr, "panic: ");
  if (ptr != 0 && len > 0) {
    (void)fwrite((const void *)ptr, 1, (size_t)len, stderr);
  }
  (void)fputc('\n', stderr);
  (void)fflush(stderr);
  _Exit(101);
}

double astra_fmod(double x, double y) {
  return fmod(x, y);
}

typedef struct {
  size_t len;
  size_t cap;
  uintptr_t *items;
} AstraList;

typedef struct {
  size_t len;
  size_t cap;
  uintptr_t *keys;
  uintptr_t *vals;
} AstraMap;

typedef struct {
  uintptr_t handle;
  int kind;
  void *ptr;
} ObjEntry;

static ObjEntry *g_objs = NULL;
static size_t g_objs_len = 0;
static size_t g_objs_cap = 0;
static uintptr_t g_next_handle = 0x7000000000000001ULL;

enum {
  OBJ_KIND_LIST = 1,
  OBJ_KIND_MAP = 2,
};

typedef enum {
  ASTRA_ANY_NONE = 0,
  ASTRA_ANY_INT = 1,
  ASTRA_ANY_BOOL = 2,
  ASTRA_ANY_FLOAT = 3,
  ASTRA_ANY_STR = 4,
  ASTRA_ANY_PTR = 5,
  ASTRA_ANY_LIST = 6,
  ASTRA_ANY_MAP = 7,
} AstraAnyTag;

typedef struct {
  uintptr_t handle;
  AstraAnyTag tag;
  union {
    int64_t i64;
    double f64;
    uintptr_t ptr;
    _Bool b;
  } value;
} AstraAnyEntry;

static AstraAnyEntry *g_any = NULL;
static size_t g_any_len = 0;
static size_t g_any_cap = 0;
static uintptr_t g_next_any_handle = 0x5000000000000001ULL;

static bool astra_any_reserve(size_t want) {
  if (g_any_cap >= want) {
    return true;
  }
  size_t next = g_any_cap == 0 ? 16 : g_any_cap * 2;
  while (next < want) {
    next *= 2;
  }
  AstraAnyEntry *p = (AstraAnyEntry *)realloc(g_any, next * sizeof(AstraAnyEntry));
  if (p == NULL) {
    return false;
  }
  g_any = p;
  g_any_cap = next;
  return true;
}

static AstraAnyEntry *astra_any_find(uintptr_t handle) {
  for (size_t i = 0; i < g_any_len; i++) {
    if (g_any[i].handle == handle) {
      return &g_any[i];
    }
  }
  return NULL;
}

static uintptr_t astra_any_alloc(AstraAnyTag tag) {
  if (!astra_any_reserve(g_any_len + 1)) {
    return 0;
  }
  uintptr_t h = g_next_any_handle;
  g_next_any_handle += 2;
  g_any[g_any_len].handle = h;
  g_any[g_any_len].tag = tag;
  g_any[g_any_len].value.ptr = 0;
  g_any_len += 1;
  return h;
}

static AstraAnyEntry *astra_any_expect(uintptr_t handle) {
  AstraAnyEntry *entry = astra_any_find(handle);
  if (entry == NULL) {
    astra_trap();
  }
  return entry;
}

static int64_t astra_sat_f64_to_i64(double v) {
  if (isnan(v)) {
    return 0;
  }
  if (isinf(v)) {
    return v > 0.0 ? INT64_MAX : INT64_MIN;
  }
  if (v >= (double)INT64_MAX) {
    return INT64_MAX;
  }
  if (v <= (double)INT64_MIN) {
    return INT64_MIN;
  }
  return (int64_t)trunc(v);
}

uintptr_t astra_any_box_i64(int64_t value) {
  uintptr_t h = astra_any_alloc(ASTRA_ANY_INT);
  if (h == 0) {
    return 0;
  }
  AstraAnyEntry *entry = astra_any_expect(h);
  entry->value.i64 = value;
  return h;
}

uintptr_t astra_any_box_bool(_Bool value) {
  uintptr_t h = astra_any_alloc(ASTRA_ANY_BOOL);
  if (h == 0) {
    return 0;
  }
  AstraAnyEntry *entry = astra_any_expect(h);
  entry->value.b = value ? 1 : 0;
  return h;
}

uintptr_t astra_any_box_f64(double value) {
  uintptr_t h = astra_any_alloc(ASTRA_ANY_FLOAT);
  if (h == 0) {
    return 0;
  }
  AstraAnyEntry *entry = astra_any_expect(h);
  entry->value.f64 = value;
  return h;
}

uintptr_t astra_any_box_str(uintptr_t value) {
  uintptr_t h = astra_any_alloc(ASTRA_ANY_STR);
  if (h == 0) {
    return 0;
  }
  AstraAnyEntry *entry = astra_any_expect(h);
  entry->value.ptr = value;
  return h;
}

uintptr_t astra_any_box_ptr(uintptr_t value) {
  uintptr_t h = astra_any_alloc(ASTRA_ANY_PTR);
  if (h == 0) {
    return 0;
  }
  AstraAnyEntry *entry = astra_any_expect(h);
  entry->value.ptr = value;
  return h;
}

static uintptr_t astra_any_box_obj(AstraAnyTag tag, uintptr_t handle) {
  uintptr_t h = astra_any_alloc(tag);
  if (h == 0) {
    return 0;
  }
  AstraAnyEntry *entry = astra_any_expect(h);
  entry->value.ptr = handle;
  return h;
}

uintptr_t astra_any_box_none(void) {
  uintptr_t h = astra_any_alloc(ASTRA_ANY_NONE);
  if (h == 0) {
    return 0;
  }
  AstraAnyEntry *entry = astra_any_expect(h);
  entry->value.ptr = 0;
  return h;
}

int64_t astra_any_to_i64(uintptr_t value) {
  AstraAnyEntry *entry = astra_any_expect(value);
  if (entry->tag == ASTRA_ANY_INT) {
    return entry->value.i64;
  }
  if (entry->tag == ASTRA_ANY_BOOL) {
    return entry->value.b ? 1 : 0;
  }
  if (entry->tag == ASTRA_ANY_FLOAT) {
    return astra_sat_f64_to_i64(entry->value.f64);
  }
  astra_trap();
  return 0;
}

_Bool astra_any_to_bool(uintptr_t value) {
  AstraAnyEntry *entry = astra_any_expect(value);
  if (entry->tag == ASTRA_ANY_BOOL) {
    return entry->value.b ? 1 : 0;
  }
  if (entry->tag == ASTRA_ANY_INT) {
    return entry->value.i64 != 0;
  }
  if (entry->tag == ASTRA_ANY_FLOAT) {
    return !isnan(entry->value.f64) && entry->value.f64 != 0.0;
  }
  astra_trap();
  return 0;
}

double astra_any_to_f64(uintptr_t value) {
  AstraAnyEntry *entry = astra_any_expect(value);
  if (entry->tag == ASTRA_ANY_FLOAT) {
    return entry->value.f64;
  }
  if (entry->tag == ASTRA_ANY_INT) {
    return (double)entry->value.i64;
  }
  if (entry->tag == ASTRA_ANY_BOOL) {
    return entry->value.b ? 1.0 : 0.0;
  }
  astra_trap();
  return 0.0;
}

uintptr_t astra_any_to_str(uintptr_t value) {
  AstraAnyEntry *entry = astra_any_expect(value);
  if (entry->tag == ASTRA_ANY_STR) {
    return entry->value.ptr;
  }
  astra_trap();
  return 0;
}

uintptr_t astra_any_to_ptr(uintptr_t value) {
  AstraAnyEntry *entry = astra_any_expect(value);
  if (entry->tag == ASTRA_ANY_PTR || entry->tag == ASTRA_ANY_LIST || entry->tag == ASTRA_ANY_MAP) {
    return entry->value.ptr;
  }
  astra_trap();
  return 0;
}

static _Bool astra_any_equal(uintptr_t a, uintptr_t b) {
  if (a == b) {
    return 1;
  }
  AstraAnyEntry *ea = astra_any_find(a);
  AstraAnyEntry *eb = astra_any_find(b);
  if (ea == NULL || eb == NULL) {
    return 0;
  }
  if (ea->tag != eb->tag) {
    bool a_num = ea->tag == ASTRA_ANY_INT || ea->tag == ASTRA_ANY_BOOL || ea->tag == ASTRA_ANY_FLOAT;
    bool b_num = eb->tag == ASTRA_ANY_INT || eb->tag == ASTRA_ANY_BOOL || eb->tag == ASTRA_ANY_FLOAT;
    if (a_num && b_num) {
      return astra_any_to_f64(a) == astra_any_to_f64(b);
    }
    return 0;
  }
  switch (ea->tag) {
  case ASTRA_ANY_INT:
    return ea->value.i64 == eb->value.i64;
  case ASTRA_ANY_BOOL:
    return ea->value.b == eb->value.b;
  case ASTRA_ANY_FLOAT:
    if (isnan(ea->value.f64) && isnan(eb->value.f64)) {
      return 1;
    }
    return ea->value.f64 == eb->value.f64;
  case ASTRA_ANY_STR: {
    const char *sa = (const char *)ea->value.ptr;
    const char *sb = (const char *)eb->value.ptr;
    if (sa == NULL || sb == NULL) {
      return sa == sb;
    }
    return strcmp(sa, sb) == 0;
  }
  case ASTRA_ANY_PTR:
  case ASTRA_ANY_LIST:
  case ASTRA_ANY_MAP:
    return ea->value.ptr == eb->value.ptr;
  case ASTRA_ANY_NONE:
    return 1;
  default:
    return 0;
  }
}

static bool astra_obj_reserve(size_t want) {
  if (g_objs_cap >= want) {
    return true;
  }
  size_t next = g_objs_cap == 0 ? 8 : g_objs_cap * 2;
  while (next < want) {
    next *= 2;
  }
  ObjEntry *p = (ObjEntry *)realloc(g_objs, next * sizeof(ObjEntry));
  if (p == NULL) {
    return false;
  }
  g_objs = p;
  g_objs_cap = next;
  return true;
}

static uintptr_t astra_obj_add(int kind, void *ptr) {
  if (!astra_obj_reserve(g_objs_len + 1)) {
    return 0;
  }
  uintptr_t h = g_next_handle;
  g_next_handle += 2;
  g_objs[g_objs_len].handle = h;
  g_objs[g_objs_len].kind = kind;
  g_objs[g_objs_len].ptr = ptr;
  g_objs_len += 1;
  return h;
}

static ObjEntry *astra_obj_find(uintptr_t handle) {
  for (size_t i = 0; i < g_objs_len; i++) {
    if (g_objs[i].handle == handle) {
      return &g_objs[i];
    }
  }
  return NULL;
}

static bool astra_list_reserve(AstraList *xs, size_t want) {
  if (xs->cap >= want) {
    return true;
  }
  size_t next = xs->cap == 0 ? 8 : xs->cap * 2;
  while (next < want) {
    next *= 2;
  }
  uintptr_t *p = (uintptr_t *)realloc(xs->items, next * sizeof(uintptr_t));
  if (p == NULL) {
    return false;
  }
  xs->items = p;
  xs->cap = next;
  return true;
}

static bool astra_map_reserve(AstraMap *m, size_t want) {
  if (m->cap >= want) {
    return true;
  }
  size_t next = m->cap == 0 ? 8 : m->cap * 2;
  while (next < want) {
    next *= 2;
  }
  uintptr_t *k = (uintptr_t *)realloc(m->keys, next * sizeof(uintptr_t));
  if (k == NULL) {
    return false;
  }
  uintptr_t *v = (uintptr_t *)realloc(m->vals, next * sizeof(uintptr_t));
  if (v == NULL) {
    return false;
  }
  m->keys = k;
  m->vals = v;
  m->cap = next;
  return true;
}

static AstraList *astra_expect_list(uintptr_t list_any) {
  AstraAnyEntry *any = astra_any_expect(list_any);
  if (any->tag != ASTRA_ANY_LIST) {
    astra_trap();
  }
  ObjEntry *e = astra_obj_find(any->value.ptr);
  if (e == NULL || e->kind != OBJ_KIND_LIST) {
    astra_trap();
  }
  return (AstraList *)e->ptr;
}

static AstraMap *astra_expect_map(uintptr_t map_any) {
  AstraAnyEntry *any = astra_any_expect(map_any);
  if (any->tag != ASTRA_ANY_MAP) {
    astra_trap();
  }
  ObjEntry *e = astra_obj_find(any->value.ptr);
  if (e == NULL || e->kind != OBJ_KIND_MAP) {
    astra_trap();
  }
  return (AstraMap *)e->ptr;
}

uintptr_t astra_list_new(void) {
  AstraList *xs = (AstraList *)calloc(1, sizeof(AstraList));
  if (xs == NULL) {
    return 0;
  }
  uintptr_t obj_h = astra_obj_add(OBJ_KIND_LIST, xs);
  if (obj_h == 0) {
    return 0;
  }
  return astra_any_box_obj(ASTRA_ANY_LIST, obj_h);
}

uintptr_t astra_list_push(uintptr_t list_h, uintptr_t value) {
  AstraList *xs = astra_expect_list(list_h);
  if (!astra_list_reserve(xs, xs->len + 1)) {
    return (uintptr_t)-1;
  }
  xs->items[xs->len++] = value;
  return 0;
}

uintptr_t astra_list_get(uintptr_t list_h, uintptr_t index) {
  AstraList *xs = astra_expect_list(list_h);
  size_t i = (size_t)index;
  if (i >= xs->len) {
    return astra_any_box_i64(0);
  }
  return xs->items[i];
}

uintptr_t astra_list_set(uintptr_t list_h, uintptr_t index, uintptr_t value) {
  AstraList *xs = astra_expect_list(list_h);
  size_t i = (size_t)index;
  if (i >= xs->len) {
    return (uintptr_t)-1;
  }
  xs->items[i] = value;
  return 0;
}

uintptr_t astra_list_len(uintptr_t list_h) {
  AstraList *xs = astra_expect_list(list_h);
  return (uintptr_t)xs->len;
}

uintptr_t astra_map_new(void) {
  AstraMap *m = (AstraMap *)calloc(1, sizeof(AstraMap));
  if (m == NULL) {
    return 0;
  }
  uintptr_t obj_h = astra_obj_add(OBJ_KIND_MAP, m);
  if (obj_h == 0) {
    return 0;
  }
  return astra_any_box_obj(ASTRA_ANY_MAP, obj_h);
}

_Bool astra_map_has(uintptr_t map_h, uintptr_t key) {
  AstraMap *m = astra_expect_map(map_h);
  for (size_t i = 0; i < m->len; i++) {
    if (astra_any_equal(m->keys[i], key)) {
      return 1;
    }
  }
  return 0;
}

uintptr_t astra_map_get(uintptr_t map_h, uintptr_t key) {
  AstraMap *m = astra_expect_map(map_h);
  for (size_t i = 0; i < m->len; i++) {
    if (astra_any_equal(m->keys[i], key)) {
      return m->vals[i];
    }
  }
  return astra_any_box_i64(0);
}

uintptr_t astra_map_set(uintptr_t map_h, uintptr_t key, uintptr_t value) {
  AstraMap *m = astra_expect_map(map_h);
  for (size_t i = 0; i < m->len; i++) {
    if (astra_any_equal(m->keys[i], key)) {
      m->vals[i] = value;
      return 0;
    }
  }
  if (!astra_map_reserve(m, m->len + 1)) {
    return (uintptr_t)-1;
  }
  m->keys[m->len] = key;
  m->vals[m->len] = value;
  m->len += 1;
  return 0;
}

uintptr_t astra_len_any(uintptr_t v) {
  AstraAnyEntry *entry = astra_any_find(v);
  if (entry == NULL) {
    return 0;
  }
  if (entry->tag == ASTRA_ANY_LIST) {
    AstraList *xs = astra_expect_list(v);
    return (uintptr_t)xs->len;
  }
  if (entry->tag == ASTRA_ANY_MAP) {
    AstraMap *m = astra_expect_map(v);
    return (uintptr_t)m->len;
  }
  if (entry->tag == ASTRA_ANY_STR) {
    const char *s = (const char *)entry->value.ptr;
    return s == NULL ? 0 : (uintptr_t)strlen(s);
  }
  return 0;
}

uintptr_t astra_len_str(uintptr_t s) {
  if (s == 0) {
    return 0;
  }
  return (uintptr_t)strlen((const char *)s);
}

uintptr_t astra_str_concat(uintptr_t a_ptr, uintptr_t b_ptr) {
  const char *a = (const char *)a_ptr;
  const char *b = (const char *)b_ptr;
  if (a == NULL) {
    a = "";
  }
  if (b == NULL) {
    b = "";
  }
  size_t na = strlen(a);
  size_t nb = strlen(b);
  char *out = (char *)astra_heap_alloc(na + nb + 1);
  if (out == NULL) {
    return (uintptr_t)astra_strdup_s("");
  }
  memcpy(out, a, na);
  memcpy(out + na, b, nb);
  out[na + nb] = '\0';
  return (uintptr_t)out;
}

uintptr_t astra_read_file(uintptr_t path_ptr) {
  const char *path = (const char *)path_ptr;
  if (path == NULL) {
    return (uintptr_t)astra_strdup_s("");
  }
  FILE *f = fopen(path, "rb");
  if (f == NULL) {
    return (uintptr_t)astra_strdup_s("");
  }
  if (fseek(f, 0, SEEK_END) != 0) {
    fclose(f);
    return (uintptr_t)astra_strdup_s("");
  }
  long n = ftell(f);
  if (n < 0) {
    fclose(f);
    return (uintptr_t)astra_strdup_s("");
  }
  if (fseek(f, 0, SEEK_SET) != 0) {
    fclose(f);
    return (uintptr_t)astra_strdup_s("");
  }
  char *buf = (char *)astra_heap_alloc((size_t)n + 1);
  if (buf == NULL) {
    fclose(f);
    return (uintptr_t)astra_strdup_s("");
  }
  size_t got = fread(buf, 1, (size_t)n, f);
  buf[got] = '\0';
  fclose(f);
  return (uintptr_t)buf;
}

uintptr_t astra_write_file(uintptr_t path_ptr, uintptr_t data_ptr) {
  const char *path = (const char *)path_ptr;
  const char *data = (const char *)data_ptr;
  if (path == NULL || data == NULL) {
    return (uintptr_t)-1;
  }
  FILE *f = fopen(path, "wb");
  if (f == NULL) {
    return (uintptr_t)-1;
  }
  size_t n = strlen(data);
  size_t wr = fwrite(data, 1, n, f);
  fclose(f);
  return (uintptr_t)wr;
}

static char **g_cli_argv = NULL;
static size_t g_cli_argc = 0;
static bool g_cli_loaded = false;

static void astra_load_cli_args(void) {
  if (g_cli_loaded) {
    return;
  }
  g_cli_loaded = true;
#if defined(__linux__)
  FILE *f = fopen("/proc/self/cmdline", "rb");
  if (f == NULL) {
    return;
  }
  if (fseek(f, 0, SEEK_END) != 0) {
    fclose(f);
    return;
  }
  long n = ftell(f);
  if (n <= 0) {
    fclose(f);
    return;
  }
  if (fseek(f, 0, SEEK_SET) != 0) {
    fclose(f);
    return;
  }
  char *buf = (char *)malloc((size_t)n);
  if (buf == NULL) {
    fclose(f);
    return;
  }
  size_t got = fread(buf, 1, (size_t)n, f);
  fclose(f);
  if (got == 0) {
    free(buf);
    return;
  }

  size_t count = 0;
  for (size_t i = 0; i < got; i++) {
    if (buf[i] == '\0') {
      count += 1;
    }
  }
  if (count == 0) {
    free(buf);
    return;
  }
  char **arr = (char **)calloc(count, sizeof(char *));
  if (arr == NULL) {
    free(buf);
    return;
  }
  size_t idx = 0;
  size_t start = 0;
  for (size_t i = 0; i < got && idx < count; i++) {
    if (buf[i] == '\0') {
      size_t len = i - start;
      char *s = (char *)malloc(len + 1);
      if (s == NULL) {
        break;
      }
      memcpy(s, buf + start, len);
      s[len] = '\0';
      arr[idx++] = s;
      start = i + 1;
    }
  }
  free(buf);
  g_cli_argv = arr;
  g_cli_argc = idx;
#endif
}

uintptr_t astra_args(void) {
  astra_load_cli_args();
  uintptr_t h = astra_list_new();
  for (size_t i = 0; i < g_cli_argc; i++) {
    astra_list_push(h, astra_any_box_str((uintptr_t)g_cli_argv[i]));
  }
  return h;
}

uintptr_t astra_arg(uintptr_t i) {
  astra_load_cli_args();
  size_t idx = (size_t)i;
  if (idx >= g_cli_argc) {
    return (uintptr_t)astra_strdup_s("");
  }
  return (uintptr_t)g_cli_argv[idx];
}

typedef struct {
  uintptr_t value;
  bool used;
} SpawnEntry;

static SpawnEntry *g_spawn = NULL;
static size_t g_spawn_cap = 0;
static uintptr_t g_next_tid = 1;

static bool astra_spawn_reserve(size_t want) {
  if (g_spawn_cap >= want) {
    return true;
  }
  size_t next = g_spawn_cap == 0 ? 8 : g_spawn_cap * 2;
  while (next < want) {
    next *= 2;
  }
  SpawnEntry *p = (SpawnEntry *)realloc(g_spawn, next * sizeof(SpawnEntry));
  if (p == NULL) {
    return false;
  }
  for (size_t i = g_spawn_cap; i < next; i++) {
    p[i].value = 0;
    p[i].used = false;
  }
  g_spawn = p;
  g_spawn_cap = next;
  return true;
}

uintptr_t astra_spawn_store(uintptr_t value) {
  uintptr_t tid = g_next_tid++;
  size_t idx = (size_t)tid;
  if (!astra_spawn_reserve(idx + 1)) {
    return 0;
  }
  g_spawn[idx].value = value;
  g_spawn[idx].used = true;
  return tid;
}

uintptr_t astra_join(uintptr_t tid) {
  size_t idx = (size_t)tid;
  if (idx >= g_spawn_cap || !g_spawn[idx].used) {
    return astra_any_box_i64(0);
  }
  return g_spawn[idx].value;
}

_Bool astra_file_exists(uintptr_t path_ptr) {
  const char *path = (const char *)path_ptr;
  if (path == NULL) {
    return 0;
  }
  return access(path, F_OK) == 0;
}

uintptr_t astra_file_remove(uintptr_t path_ptr) {
  const char *path = (const char *)path_ptr;
  if (path == NULL) {
    return (uintptr_t)-1;
  }
  return remove(path) == 0 ? 0 : (uintptr_t)-1;
}

uintptr_t astra_tcp_connect(uintptr_t addr_ptr) {
  (void)addr_ptr;
  return (uintptr_t)-1;
}

uintptr_t astra_tcp_send(uintptr_t sid, uintptr_t data_ptr) {
  (void)sid;
  (void)data_ptr;
  return (uintptr_t)-1;
}

uintptr_t astra_tcp_recv(uintptr_t sid, uintptr_t n) {
  (void)sid;
  (void)n;
  return (uintptr_t)astra_strdup_s("");
}

uintptr_t astra_tcp_close(uintptr_t sid) {
  (void)sid;
  return 0;
}

static uint64_t astra_fnv1a(const char *s) {
  const uint64_t off = 1469598103934665603ULL;
  const uint64_t prime = 1099511628211ULL;
  uint64_t h = off;
  if (s == NULL) {
    return h;
  }
  for (const unsigned char *p = (const unsigned char *)s; *p != 0; ++p) {
    h ^= (uint64_t)(*p);
    h *= prime;
  }
  return h;
}

static char *astra_hex64x4(uint64_t a, uint64_t b, uint64_t c, uint64_t d) {
  char *out = (char *)astra_heap_alloc(65);
  if (out == NULL) {
    return NULL;
  }
  (void)snprintf(out, 65, "%016llx%016llx%016llx%016llx",
                 (unsigned long long)a,
                 (unsigned long long)b,
                 (unsigned long long)c,
                 (unsigned long long)d);
  return out;
}

typedef struct {
  char *data;
  size_t len;
  size_t cap;
} AstraBuf;

static bool astra_buf_reserve(AstraBuf *buf, size_t want) {
  if (buf->cap >= want) {
    return true;
  }
  size_t next = buf->cap == 0 ? 64 : buf->cap * 2;
  while (next < want) {
    next *= 2;
  }
  char *p = (char *)realloc(buf->data, next);
  if (p == NULL) {
    return false;
  }
  buf->data = p;
  buf->cap = next;
  return true;
}

static bool astra_buf_append_n(AstraBuf *buf, const char *text, size_t n) {
  if (!astra_buf_reserve(buf, buf->len + n + 1)) {
    return false;
  }
  memcpy(buf->data + buf->len, text, n);
  buf->len += n;
  buf->data[buf->len] = '\0';
  return true;
}

static bool astra_buf_append(AstraBuf *buf, const char *text) {
  return astra_buf_append_n(buf, text, strlen(text));
}

static bool astra_buf_append_ch(AstraBuf *buf, char ch) {
  if (!astra_buf_reserve(buf, buf->len + 2)) {
    return false;
  }
  buf->data[buf->len++] = ch;
  buf->data[buf->len] = '\0';
  return true;
}

static char *astra_buf_finish_heap(AstraBuf *buf) {
  if (buf->data == NULL) {
    return astra_strdup_s("");
  }
  char *out = (char *)astra_heap_alloc(buf->len + 1);
  if (out == NULL) {
    free(buf->data);
    return astra_strdup_s("");
  }
  memcpy(out, buf->data, buf->len + 1);
  free(buf->data);
  return out;
}

static bool astra_json_write_escaped_string(AstraBuf *buf, const char *s) {
  if (!astra_buf_append_ch(buf, '"')) {
    return false;
  }
  if (s != NULL) {
    for (const unsigned char *p = (const unsigned char *)s; *p != 0; ++p) {
      switch (*p) {
      case '"':
        if (!astra_buf_append(buf, "\\\"")) {
          return false;
        }
        break;
      case '\\':
        if (!astra_buf_append(buf, "\\\\")) {
          return false;
        }
        break;
      case '\b':
        if (!astra_buf_append(buf, "\\b")) {
          return false;
        }
        break;
      case '\f':
        if (!astra_buf_append(buf, "\\f")) {
          return false;
        }
        break;
      case '\n':
        if (!astra_buf_append(buf, "\\n")) {
          return false;
        }
        break;
      case '\r':
        if (!astra_buf_append(buf, "\\r")) {
          return false;
        }
        break;
      case '\t':
        if (!astra_buf_append(buf, "\\t")) {
          return false;
        }
        break;
      default:
        if (*p < 0x20) {
          char hex[7];
          (void)snprintf(hex, sizeof(hex), "\\u%04x", (unsigned int)(*p));
          if (!astra_buf_append(buf, hex)) {
            return false;
          }
        } else if (!astra_buf_append_ch(buf, (char)*p)) {
          return false;
        }
        break;
      }
    }
  }
  return astra_buf_append_ch(buf, '"');
}

static bool astra_json_write_map_key(AstraBuf *buf, uintptr_t key_any);

static bool astra_json_write_any(AstraBuf *buf, uintptr_t v, int depth) {
  if (depth > 256) {
    return astra_buf_append(buf, "null");
  }
  AstraAnyEntry *entry = astra_any_find(v);
  if (entry == NULL) {
    return astra_buf_append(buf, "null");
  }
  char num[64];
  switch (entry->tag) {
  case ASTRA_ANY_NONE:
    return astra_buf_append(buf, "null");
  case ASTRA_ANY_INT:
    (void)snprintf(num, sizeof(num), "%lld", (long long)entry->value.i64);
    return astra_buf_append(buf, num);
  case ASTRA_ANY_BOOL:
    return astra_buf_append(buf, entry->value.b ? "true" : "false");
  case ASTRA_ANY_FLOAT:
    if (isnan(entry->value.f64) || isinf(entry->value.f64)) {
      return astra_buf_append(buf, "null");
    }
    (void)snprintf(num, sizeof(num), "%.17g", entry->value.f64);
    return astra_buf_append(buf, num);
  case ASTRA_ANY_STR:
    return astra_json_write_escaped_string(buf, (const char *)entry->value.ptr);
  case ASTRA_ANY_PTR:
    (void)snprintf(num, sizeof(num), "%llu", (unsigned long long)entry->value.ptr);
    return astra_buf_append(buf, num);
  case ASTRA_ANY_LIST: {
    AstraList *xs = astra_expect_list(v);
    if (!astra_buf_append_ch(buf, '[')) {
      return false;
    }
    for (size_t i = 0; i < xs->len; i++) {
      if (i > 0 && !astra_buf_append_ch(buf, ',')) {
        return false;
      }
      if (!astra_json_write_any(buf, xs->items[i], depth + 1)) {
        return false;
      }
    }
    return astra_buf_append_ch(buf, ']');
  }
  case ASTRA_ANY_MAP: {
    AstraMap *m = astra_expect_map(v);
    if (!astra_buf_append_ch(buf, '{')) {
      return false;
    }
    for (size_t i = 0; i < m->len; i++) {
      if (i > 0 && !astra_buf_append_ch(buf, ',')) {
        return false;
      }
      if (!astra_json_write_map_key(buf, m->keys[i])) {
        return false;
      }
      if (!astra_buf_append_ch(buf, ':')) {
        return false;
      }
      if (!astra_json_write_any(buf, m->vals[i], depth + 1)) {
        return false;
      }
    }
    return astra_buf_append_ch(buf, '}');
  }
  default:
    return astra_buf_append(buf, "null");
  }
}

static bool astra_json_write_map_key(AstraBuf *buf, uintptr_t key_any) {
  AstraAnyEntry *entry = astra_any_find(key_any);
  if (entry == NULL) {
    return astra_json_write_escaped_string(buf, "null");
  }
  char num[64];
  switch (entry->tag) {
  case ASTRA_ANY_STR:
    return astra_json_write_escaped_string(buf, (const char *)entry->value.ptr);
  case ASTRA_ANY_INT:
    (void)snprintf(num, sizeof(num), "%lld", (long long)entry->value.i64);
    return astra_json_write_escaped_string(buf, num);
  case ASTRA_ANY_BOOL:
    return astra_json_write_escaped_string(buf, entry->value.b ? "true" : "false");
  case ASTRA_ANY_FLOAT:
    if (isnan(entry->value.f64) || isinf(entry->value.f64)) {
      return astra_json_write_escaped_string(buf, "null");
    }
    (void)snprintf(num, sizeof(num), "%.17g", entry->value.f64);
    return astra_json_write_escaped_string(buf, num);
  case ASTRA_ANY_NONE:
    return astra_json_write_escaped_string(buf, "null");
  case ASTRA_ANY_PTR:
  case ASTRA_ANY_LIST:
  case ASTRA_ANY_MAP:
    (void)snprintf(num, sizeof(num), "%llu", (unsigned long long)entry->value.ptr);
    return astra_json_write_escaped_string(buf, num);
  default:
    return astra_json_write_escaped_string(buf, "null");
  }
}

uintptr_t astra_to_json(uintptr_t v) {
  AstraBuf buf = {0};
  if (!astra_json_write_any(&buf, v, 0)) {
    free(buf.data);
    return (uintptr_t)astra_strdup_s("null");
  }
  return (uintptr_t)astra_buf_finish_heap(&buf);
}

typedef struct {
  const char *s;
  size_t i;
} AstraJsonCursor;

static void astra_json_skip_ws(AstraJsonCursor *c) {
  while (c->s[c->i] == ' ' || c->s[c->i] == '\n' || c->s[c->i] == '\r' || c->s[c->i] == '\t') {
    c->i++;
  }
}

static int astra_json_hex_nibble(char ch) {
  if (ch >= '0' && ch <= '9') {
    return ch - '0';
  }
  if (ch >= 'a' && ch <= 'f') {
    return 10 + (ch - 'a');
  }
  if (ch >= 'A' && ch <= 'F') {
    return 10 + (ch - 'A');
  }
  return -1;
}

static char *astra_json_parse_string(AstraJsonCursor *c) {
  if (c->s[c->i] != '"') {
    return NULL;
  }
  c->i += 1;
  AstraBuf out = {0};
  while (c->s[c->i] != '\0') {
    char ch = c->s[c->i++];
    if (ch == '"') {
      return astra_buf_finish_heap(&out);
    }
    if (ch == '\\') {
      char esc = c->s[c->i++];
      switch (esc) {
      case '"':
      case '\\':
      case '/':
        if (!astra_buf_append_ch(&out, esc)) {
          free(out.data);
          return NULL;
        }
        continue;
      case 'b':
        if (!astra_buf_append_ch(&out, '\b')) {
          free(out.data);
          return NULL;
        }
        continue;
      case 'f':
        if (!astra_buf_append_ch(&out, '\f')) {
          free(out.data);
          return NULL;
        }
        continue;
      case 'n':
        if (!astra_buf_append_ch(&out, '\n')) {
          free(out.data);
          return NULL;
        }
        continue;
      case 'r':
        if (!astra_buf_append_ch(&out, '\r')) {
          free(out.data);
          return NULL;
        }
        continue;
      case 't':
        if (!astra_buf_append_ch(&out, '\t')) {
          free(out.data);
          return NULL;
        }
        continue;
      case 'u': {
        if (
            c->s[c->i + 0] == '\0' || c->s[c->i + 1] == '\0' || c->s[c->i + 2] == '\0' || c->s[c->i + 3] == '\0') {
          free(out.data);
          return NULL;
        }
        int h0 = astra_json_hex_nibble(c->s[c->i + 0]);
        int h1 = astra_json_hex_nibble(c->s[c->i + 1]);
        int h2 = astra_json_hex_nibble(c->s[c->i + 2]);
        int h3 = astra_json_hex_nibble(c->s[c->i + 3]);
        if (h0 < 0 || h1 < 0 || h2 < 0 || h3 < 0) {
          free(out.data);
          return NULL;
        }
        c->i += 4;
        int code = (h0 << 12) | (h1 << 8) | (h2 << 4) | h3;
        char cp = code >= 0 && code <= 0x7f ? (char)code : '?';
        if (!astra_buf_append_ch(&out, cp)) {
          free(out.data);
          return NULL;
        }
        continue;
      }
      default:
        free(out.data);
        return NULL;
      }
    }
    if ((unsigned char)ch < 0x20) {
      free(out.data);
      return NULL;
    }
    if (!astra_buf_append_ch(&out, ch)) {
      free(out.data);
      return NULL;
    }
  }
  free(out.data);
  return NULL;
}

static uintptr_t astra_json_parse_value(AstraJsonCursor *c);

static uintptr_t astra_json_parse_array(AstraJsonCursor *c) {
  if (c->s[c->i] != '[') {
    return 0;
  }
  c->i += 1;
  uintptr_t list_any = astra_list_new();
  if (list_any == 0) {
    return 0;
  }
  astra_json_skip_ws(c);
  if (c->s[c->i] == ']') {
    c->i += 1;
    return list_any;
  }
  while (true) {
    uintptr_t v = astra_json_parse_value(c);
    if (v == 0) {
      return 0;
    }
    (void)astra_list_push(list_any, v);
    astra_json_skip_ws(c);
    if (c->s[c->i] == ',') {
      c->i += 1;
      astra_json_skip_ws(c);
      continue;
    }
    if (c->s[c->i] == ']') {
      c->i += 1;
      return list_any;
    }
    return 0;
  }
}

static uintptr_t astra_json_parse_object(AstraJsonCursor *c) {
  if (c->s[c->i] != '{') {
    return 0;
  }
  c->i += 1;
  uintptr_t map_any = astra_map_new();
  if (map_any == 0) {
    return 0;
  }
  astra_json_skip_ws(c);
  if (c->s[c->i] == '}') {
    c->i += 1;
    return map_any;
  }
  while (true) {
    astra_json_skip_ws(c);
    char *k = astra_json_parse_string(c);
    if (k == NULL) {
      return 0;
    }
    astra_json_skip_ws(c);
    if (c->s[c->i] != ':') {
      return 0;
    }
    c->i += 1;
    astra_json_skip_ws(c);
    uintptr_t v = astra_json_parse_value(c);
    if (v == 0) {
      return 0;
    }
    uintptr_t key_any = astra_any_box_str((uintptr_t)k);
    (void)astra_map_set(map_any, key_any, v);
    astra_json_skip_ws(c);
    if (c->s[c->i] == ',') {
      c->i += 1;
      astra_json_skip_ws(c);
      continue;
    }
    if (c->s[c->i] == '}') {
      c->i += 1;
      return map_any;
    }
    return 0;
  }
}

static uintptr_t astra_json_parse_number(AstraJsonCursor *c) {
  const char *start = c->s + c->i;
  char *end = NULL;
  errno = 0;
  double dv = strtod(start, &end);
  if (end == start) {
    return 0;
  }
  size_t consumed = (size_t)(end - start);
  bool has_frac_or_exp = false;
  for (size_t i = 0; i < consumed; i++) {
    char ch = start[i];
    if (ch == '.' || ch == 'e' || ch == 'E') {
      has_frac_or_exp = true;
      break;
    }
  }
  c->i += consumed;
  if (!has_frac_or_exp) {
    errno = 0;
    char *iend = NULL;
    long long iv = strtoll(start, &iend, 10);
    if (errno == 0 && iend == end) {
      return astra_any_box_i64((int64_t)iv);
    }
  }
  if (isnan(dv) || isinf(dv)) {
    return astra_any_box_none();
  }
  return astra_any_box_f64(dv);
}

static uintptr_t astra_json_parse_value(AstraJsonCursor *c) {
  astra_json_skip_ws(c);
  char ch = c->s[c->i];
  if (ch == '\0') {
    return 0;
  }
  if (ch == '"') {
    char *s = astra_json_parse_string(c);
    if (s == NULL) {
      return 0;
    }
    return astra_any_box_str((uintptr_t)s);
  }
  if (ch == '[') {
    return astra_json_parse_array(c);
  }
  if (ch == '{') {
    return astra_json_parse_object(c);
  }
  if (ch == 't' && strncmp(c->s + c->i, "true", 4) == 0) {
    c->i += 4;
    return astra_any_box_bool(1);
  }
  if (ch == 'f' && strncmp(c->s + c->i, "false", 5) == 0) {
    c->i += 5;
    return astra_any_box_bool(0);
  }
  if (ch == 'n' && strncmp(c->s + c->i, "null", 4) == 0) {
    c->i += 4;
    return astra_any_box_none();
  }
  if (ch == '-' || (ch >= '0' && ch <= '9')) {
    return astra_json_parse_number(c);
  }
  return 0;
}

uintptr_t astra_from_json(uintptr_t s_ptr) {
  const char *s = (const char *)s_ptr;
  if (s == NULL) {
    return astra_any_box_none();
  }
  AstraJsonCursor c = {.s = s, .i = 0};
  uintptr_t out = astra_json_parse_value(&c);
  if (out == 0) {
    return astra_any_box_none();
  }
  astra_json_skip_ws(&c);
  if (c.s[c.i] != '\0') {
    return astra_any_box_none();
  }
  return out;
}

uintptr_t astra_sha256(uintptr_t s_ptr) {
  const char *s = (const char *)s_ptr;
  uint64_t h = astra_fnv1a(s);
  return (uintptr_t)astra_hex64x4(h, h ^ 0x9e3779b97f4a7c15ULL, h ^ 0x243f6a8885a308d3ULL, h ^ 0xb7e151628aed2a6bULL);
}

uintptr_t astra_hmac_sha256(uintptr_t k_ptr, uintptr_t s_ptr) {
  const char *k = (const char *)k_ptr;
  const char *s = (const char *)s_ptr;
  uint64_t hk = astra_fnv1a(k);
  uint64_t hs = astra_fnv1a(s);
  uint64_t x = hk ^ (hs + 0x9e3779b97f4a7c15ULL + (hk << 6) + (hk >> 2));
  return (uintptr_t)astra_hex64x4(x, hk, hs, x ^ hk ^ hs);
}


static bool astra_is_valid_utf8(const unsigned char *s, size_t n) {
  size_t i = 0;
  while (i < n) {
    unsigned char c = s[i];
    if (c <= 0x7F) {
      i += 1;
      continue;
    }
    if ((c & 0xE0) == 0xC0) {
      if (i + 1 >= n) return false;
      unsigned char c1 = s[i + 1];
      if ((c1 & 0xC0) != 0x80 || c < 0xC2) return false;
      i += 2;
      continue;
    }
    if ((c & 0xF0) == 0xE0) {
      if (i + 2 >= n) return false;
      unsigned char c1 = s[i + 1], c2 = s[i + 2];
      if ((c1 & 0xC0) != 0x80 || (c2 & 0xC0) != 0x80) return false;
      if (c == 0xE0 && c1 < 0xA0) return false;
      if (c == 0xED && c1 >= 0xA0) return false;
      i += 3;
      continue;
    }
    if ((c & 0xF8) == 0xF0) {
      if (i + 3 >= n) return false;
      unsigned char c1 = s[i + 1], c2 = s[i + 2], c3 = s[i + 3];
      if ((c1 & 0xC0) != 0x80 || (c2 & 0xC0) != 0x80 || (c3 & 0xC0) != 0x80) return false;
      if (c == 0xF0 && c1 < 0x90) return false;
      if (c > 0xF4 || (c == 0xF4 && c1 >= 0x90)) return false;
      i += 4;
      continue;
    }
    return false;
  }
  return true;
}

typedef struct {
  uint64_t len;
  unsigned char *data;
} AstraSliceHeader;

uintptr_t astra_secure_bytes(uintptr_t n_raw) {
  uint64_t n = (uint64_t)n_raw;
  AstraSliceHeader *hdr = (AstraSliceHeader *)astra_heap_alloc(sizeof(AstraSliceHeader));
  if (hdr == NULL) {
    return 0;
  }
  hdr->len = n;
  hdr->data = NULL;
  if (n == 0) {
    return (uintptr_t)hdr;
  }
  unsigned char *buf = (unsigned char *)astra_heap_alloc((size_t)n);
  if (buf == NULL) {
    return 0;
  }
  FILE *fp = fopen("/dev/urandom", "rb");
  if (fp == NULL) {
    return 0;
  }
  size_t got = fread(buf, 1, (size_t)n, fp);
  fclose(fp);
  if (got != (size_t)n) {
    return 0;
  }
  hdr->data = buf;
  return (uintptr_t)hdr;
}

uintptr_t astra_utf8_encode(uintptr_t s_ptr) {
  const char *s = (const char *)s_ptr;
  if (s == NULL) {
    return astra_secure_bytes(0);
  }
  size_t n = strlen(s);
  AstraSliceHeader *hdr = (AstraSliceHeader *)astra_heap_alloc(sizeof(AstraSliceHeader));
  if (hdr == NULL) {
    return 0;
  }
  hdr->len = (uint64_t)n;
  hdr->data = NULL;
  if (n == 0) {
    return (uintptr_t)hdr;
  }
  unsigned char *buf = (unsigned char *)astra_heap_alloc(n);
  if (buf == NULL) {
    return 0;
  }
  memcpy(buf, s, n);
  hdr->data = buf;
  return (uintptr_t)hdr;
}

uintptr_t astra_utf8_decode(uintptr_t bytes_ptr) {
  AstraSliceHeader *hdr = (AstraSliceHeader *)bytes_ptr;
  if (hdr == NULL) {
    return 0;
  }
  size_t n = (size_t)hdr->len;
  const unsigned char *data = (const unsigned char *)hdr->data;
  if (n > 0 && data == NULL) {
    return 0;
  }
  if (!astra_is_valid_utf8(data, n)) {
    return 0;
  }
  char *out = (char *)astra_heap_alloc(n + 1);
  if (out == NULL) {
    return 0;
  }
  if (n > 0) {
    memcpy(out, data, n);
  }
  out[n] = '\0';
  uintptr_t *opt = (uintptr_t *)astra_heap_alloc(sizeof(uintptr_t));
  if (opt == NULL) {
    return 0;
  }
  *opt = (uintptr_t)out;
  return (uintptr_t)opt;
}

uintptr_t astra_env_get(uintptr_t key_ptr) {
  const char *k = (const char *)key_ptr;
  if (k == NULL) {
    return (uintptr_t)astra_strdup_s("");
  }
  const char *v = getenv(k);
  if (v == NULL) {
    return (uintptr_t)astra_strdup_s("");
  }
  return (uintptr_t)astra_strdup_s(v);
}

uintptr_t astra_cwd(void) {
  char buf[4096];
  if (getcwd(buf, sizeof(buf)) == NULL) {
    return (uintptr_t)astra_strdup_s("");
  }
  return (uintptr_t)astra_strdup_s(buf);
}

uintptr_t astra_proc_run(uintptr_t cmd_ptr) {
  const char *cmd = (const char *)cmd_ptr;
  if (cmd == NULL) {
    return (uintptr_t)-1;
  }
  int rc = system(cmd);
  return (uintptr_t)rc;
}

uintptr_t astra_now_unix(void) {
  return (uintptr_t)time(NULL);
}

uintptr_t astra_monotonic_ms(void) {
  struct timespec ts;
#if defined(CLOCK_MONOTONIC)
  if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
    return 0;
  }
#else
  if (clock_gettime(CLOCK_REALTIME, &ts) != 0) {
    return 0;
  }
#endif
  uint64_t ms = (uint64_t)ts.tv_sec * 1000ULL + (uint64_t)(ts.tv_nsec / 1000000ULL);
  return (uintptr_t)ms;
}

uintptr_t astra_sleep_ms(uintptr_t ms) {
  struct timespec ts;
  uint64_t v = (uint64_t)ms;
  ts.tv_sec = (time_t)(v / 1000ULL);
  ts.tv_nsec = (long)((v % 1000ULL) * 1000000ULL);
  while (nanosleep(&ts, &ts) != 0 && errno == EINTR) {
  }
  return 0;
}

i128 astra_i128_mul_wrap(i128 a, i128 b) {
  return a * b;
}

i128 astra_i128_mul_trap(i128 a, i128 b) {
  i128 out = 0;
  if (__builtin_mul_overflow(a, b, &out)) {
    astra_trap();
  }
  return out;
}

u128 astra_u128_mul_wrap(u128 a, u128 b) {
  return a * b;
}

u128 astra_u128_mul_trap(u128 a, u128 b) {
  u128 out = 0;
  if (__builtin_mul_overflow(a, b, &out)) {
    astra_trap();
  }
  return out;
}

i128 astra_i128_div_wrap(i128 a, i128 b) {
  if (b == 0) {
    astra_trap();
  }
  if (a == astra_i128_min() && b == -1) {
    astra_trap();
  }
  return a / b;
}

i128 astra_i128_div_trap(i128 a, i128 b) {
  if (b == 0) {
    astra_trap();
  }
  if (a == astra_i128_min() && b == -1) {
    astra_trap();
  }
  return a / b;
}

u128 astra_u128_div_wrap(u128 a, u128 b) {
  if (b == 0) {
    astra_trap();
  }
  return a / b;
}

u128 astra_u128_div_trap(u128 a, u128 b) {
  if (b == 0) {
    astra_trap();
  }
  return a / b;
}

i128 astra_i128_mod_wrap(i128 a, i128 b) {
  if (b == 0) {
    astra_trap();
  }
  if (a == astra_i128_min() && b == -1) {
    astra_trap();
  }
  return a % b;
}

i128 astra_i128_mod_trap(i128 a, i128 b) {
  if (b == 0) {
    astra_trap();
  }
  if (a == astra_i128_min() && b == -1) {
    astra_trap();
  }
  return a % b;
}

u128 astra_u128_mod_wrap(u128 a, u128 b) {
  if (b == 0) {
    astra_trap();
  }
  return a % b;
}

u128 astra_u128_mod_trap(u128 a, u128 b) {
  if (b == 0) {
    astra_trap();
  }
  return a % b;
}


int32_t astra_cpu_has_sse4(void) {
#if defined(__x86_64__) || defined(__i386__)
  return __builtin_cpu_supports("sse4.2") ? 1 : 0;
#else
  return 0;
#endif
}

int32_t astra_cpu_has_avx2(void) {
#if defined(__x86_64__) || defined(__i386__)
  return __builtin_cpu_supports("avx2") ? 1 : 0;
#else
  return 0;
#endif
}

int32_t astra_cpu_has_avx512(void) {
#if defined(__x86_64__) || defined(__i386__)
  return __builtin_cpu_supports("avx512f") ? 1 : 0;
#else
  return 0;
#endif
}
