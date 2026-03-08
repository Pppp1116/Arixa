#include <errno.h>
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <stdatomic.h>
#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <bcrypt.h>
#include <io.h>
#include <malloc.h>
#else
#include <unistd.h>
#include <pthread.h>
#include <sched.h>
#endif
#if !defined(_WIN32)
#include <netdb.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
#endif

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
#if defined(_WIN32)
  p = _aligned_malloc(n, a);
  if (p == NULL) {
    return 0;
  }
#else
  if (posix_memalign(&p, a, n) != 0) {
    return 0;
  }
#endif
  astra_track_ptr(p);
  return (uintptr_t)p;
}

void astra_free(uintptr_t ptr, uintptr_t size, uintptr_t align) {
  (void)size;
  (void)align;
  if (ptr != 0) {
    void *p = (void *)ptr;
    astra_untrack_ptr(p);
#if defined(_WIN32)
    _aligned_free(p);
#else
    free(p);
#endif
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

_Bool astra_any_is_none(uintptr_t value) {
  AstraAnyEntry *entry = astra_any_expect(value);
  return entry->tag == ASTRA_ANY_NONE ? 1 : 0;
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
    if (isnan(ea->value.f64) || isnan(eb->value.f64)) {
      return 0;
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
  bool joined;
  bool has_thread;
#if defined(_WIN32)
  HANDLE thread;
#else
  pthread_t thread;
#endif
  bool used;
} SpawnEntry;

static SpawnEntry *g_spawn = NULL;
static size_t g_spawn_cap = 0;
static uintptr_t g_next_tid = 1;
#if defined(_WIN32)
static SRWLOCK g_spawn_lock = SRWLOCK_INIT;
#define ASTRA_SPAWN_LOCK() AcquireSRWLockExclusive(&g_spawn_lock)
#define ASTRA_SPAWN_UNLOCK() ReleaseSRWLockExclusive(&g_spawn_lock)
#else
static pthread_mutex_t g_spawn_lock = PTHREAD_MUTEX_INITIALIZER;
#define ASTRA_SPAWN_LOCK() ((void)pthread_mutex_lock(&g_spawn_lock))
#define ASTRA_SPAWN_UNLOCK() ((void)pthread_mutex_unlock(&g_spawn_lock))
#endif

typedef uintptr_t (*AstraSpawnEntryFn)(uintptr_t);

typedef struct {
  AstraSpawnEntryFn fn;
  uintptr_t arg;
} AstraSpawnThunkArg;

#if defined(_WIN32)
static DWORD WINAPI astra_spawn_trampoline(LPVOID opaque) {
  AstraSpawnThunkArg *ctx = (AstraSpawnThunkArg *)opaque;
  if (ctx == NULL || ctx->fn == NULL) {
    free(ctx);
    return 0;
  }
  AstraSpawnEntryFn fn = ctx->fn;
  uintptr_t arg = ctx->arg;
  free(ctx);
  return (DWORD)fn(arg);
}
#else
static void *astra_spawn_trampoline(void *opaque) {
  AstraSpawnThunkArg *ctx = (AstraSpawnThunkArg *)opaque;
  if (ctx == NULL || ctx->fn == NULL) {
    free(ctx);
    return (void *)0;
  }
  AstraSpawnEntryFn fn = ctx->fn;
  uintptr_t arg = ctx->arg;
  free(ctx);
  return (void *)fn(arg);
}
#endif

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
    p[i].joined = true;
    p[i].has_thread = false;
#if defined(_WIN32)
    p[i].thread = NULL;
#endif
    p[i].used = false;
  }
  g_spawn = p;
  g_spawn_cap = next;
  return true;
}

uintptr_t astra_spawn_start(uintptr_t fn_ptr, uintptr_t arg) {
  if (fn_ptr == 0) {
    return 0;
  }
  AstraSpawnThunkArg *ctx = (AstraSpawnThunkArg *)malloc(sizeof(AstraSpawnThunkArg));
  if (ctx == NULL) {
    return 0;
  }
  ctx->fn = (AstraSpawnEntryFn)fn_ptr;
  ctx->arg = arg;

  uintptr_t tid = 0;
  ASTRA_SPAWN_LOCK();
  tid = g_next_tid++;
  size_t idx = (size_t)tid;
  if (!astra_spawn_reserve(idx + 1)) {
    ASTRA_SPAWN_UNLOCK();
    free(ctx);
    return 0;
  }
  g_spawn[idx].used = true;
  g_spawn[idx].joined = false;
  g_spawn[idx].has_thread = true;
  g_spawn[idx].value = 0;
  ASTRA_SPAWN_UNLOCK();

#if defined(_WIN32)
  HANDLE thread = CreateThread(NULL, 0, astra_spawn_trampoline, (LPVOID)ctx, 0, NULL);
  if (thread == NULL) {
    ASTRA_SPAWN_LOCK();
    g_spawn[idx].used = false;
    g_spawn[idx].joined = true;
    g_spawn[idx].has_thread = false;
    ASTRA_SPAWN_UNLOCK();
    free(ctx);
    return 0;
  }
  ASTRA_SPAWN_LOCK();
  g_spawn[idx].thread = thread;
  ASTRA_SPAWN_UNLOCK();
#else
  pthread_t th;
  if (pthread_create(&th, NULL, astra_spawn_trampoline, (void *)ctx) != 0) {
    ASTRA_SPAWN_LOCK();
    g_spawn[idx].used = false;
    g_spawn[idx].joined = true;
    g_spawn[idx].has_thread = false;
    ASTRA_SPAWN_UNLOCK();
    free(ctx);
    return 0;
  }
  ASTRA_SPAWN_LOCK();
  g_spawn[idx].thread = th;
  ASTRA_SPAWN_UNLOCK();
#endif
  return tid;
}

uintptr_t astra_spawn_store(uintptr_t value) {
  ASTRA_SPAWN_LOCK();
  uintptr_t tid = g_next_tid++;
  size_t idx = (size_t)tid;
  if (!astra_spawn_reserve(idx + 1)) {
    ASTRA_SPAWN_UNLOCK();
    return 0;
  }
  g_spawn[idx].value = value;
  g_spawn[idx].joined = true;
  g_spawn[idx].has_thread = false;
  g_spawn[idx].used = true;
  ASTRA_SPAWN_UNLOCK();
  return tid;
}

uintptr_t astra_join(uintptr_t tid) {
  size_t idx = (size_t)tid;
  ASTRA_SPAWN_LOCK();
  if (idx >= g_spawn_cap || !g_spawn[idx].used) {
    ASTRA_SPAWN_UNLOCK();
    return astra_any_box_i64(0);
  }
  if (g_spawn[idx].joined) {
    uintptr_t done_value = g_spawn[idx].value;
    ASTRA_SPAWN_UNLOCK();
    return done_value;
  }
  bool has_thread = g_spawn[idx].has_thread;
#if defined(_WIN32)
  HANDLE th = g_spawn[idx].thread;
#else
  pthread_t th = g_spawn[idx].thread;
#endif
  ASTRA_SPAWN_UNLOCK();

  uintptr_t worker_raw = 0;
  if (has_thread) {
#if defined(_WIN32)
    DWORD wait_rc = WaitForSingleObject(th, INFINITE);
    if (wait_rc != WAIT_OBJECT_0) {
      return astra_any_box_i64(0);
    }
    DWORD code = 0;
    if (!GetExitCodeThread(th, &code)) {
      CloseHandle(th);
      return astra_any_box_i64(0);
    }
    CloseHandle(th);
    worker_raw = (uintptr_t)code;
#else
    void *ret_ptr = NULL;
    if (pthread_join(th, &ret_ptr) != 0) {
      return astra_any_box_i64(0);
    }
    worker_raw = (uintptr_t)ret_ptr;
#endif
  }
  uintptr_t boxed = astra_any_box_i64((int64_t)worker_raw);
  ASTRA_SPAWN_LOCK();
  g_spawn[idx].value = boxed;
  g_spawn[idx].joined = true;
  g_spawn[idx].has_thread = false;
  ASTRA_SPAWN_UNLOCK();
  return boxed;
}

typedef struct {
  _Atomic int64_t value;
} AstraAtomicInt;

static AstraAtomicInt *astra_atomic_ptr(uintptr_t handle) {
  AstraAtomicInt *cell = (AstraAtomicInt *)handle;
  if (cell == NULL) {
    astra_trap();
  }
  return cell;
}

uintptr_t astra_atomic_int_new(int64_t value) {
  AstraAtomicInt *cell = (AstraAtomicInt *)malloc(sizeof(AstraAtomicInt));
  if (cell == NULL) {
    return 0;
  }
  atomic_init(&cell->value, value);
  return (uintptr_t)cell;
}

int64_t astra_atomic_load(uintptr_t handle) {
  AstraAtomicInt *cell = astra_atomic_ptr(handle);
  return atomic_load_explicit(&cell->value, memory_order_seq_cst);
}

int64_t astra_atomic_store(uintptr_t handle, int64_t value) {
  AstraAtomicInt *cell = astra_atomic_ptr(handle);
  atomic_store_explicit(&cell->value, value, memory_order_seq_cst);
  return 0;
}

int64_t astra_atomic_fetch_add(uintptr_t handle, int64_t delta) {
  AstraAtomicInt *cell = astra_atomic_ptr(handle);
  return atomic_fetch_add_explicit(&cell->value, delta, memory_order_seq_cst);
}

_Bool astra_atomic_compare_exchange(uintptr_t handle, int64_t expected, int64_t desired) {
  AstraAtomicInt *cell = astra_atomic_ptr(handle);
  int64_t want = expected;
  return atomic_compare_exchange_strong_explicit(
      &cell->value, &want, desired, memory_order_seq_cst, memory_order_seq_cst);
}

typedef struct {
  bool used;
#if defined(_WIN32)
  SRWLOCK lock;
#else
  pthread_mutex_t lock;
#endif
} AstraMutexEntry;

static AstraMutexEntry *g_mutexes = NULL;
static size_t g_mutexes_cap = 0;
static uintptr_t g_next_mutex = 1;

static bool astra_mutex_reserve(size_t want) {
  if (g_mutexes_cap >= want) {
    return true;
  }
  size_t next = g_mutexes_cap == 0 ? 8 : g_mutexes_cap * 2;
  while (next < want) {
    next *= 2;
  }
  AstraMutexEntry *p = (AstraMutexEntry *)realloc(g_mutexes, next * sizeof(AstraMutexEntry));
  if (p == NULL) {
    return false;
  }
  for (size_t i = g_mutexes_cap; i < next; i++) {
    p[i].used = false;
  }
  g_mutexes = p;
  g_mutexes_cap = next;
  return true;
}

uintptr_t astra_mutex_new(void) {
  uintptr_t mid = g_next_mutex++;
  size_t idx = (size_t)mid;
  if (!astra_mutex_reserve(idx + 1)) {
    return 0;
  }
  g_mutexes[idx].used = true;
#if defined(_WIN32)
  InitializeSRWLock(&g_mutexes[idx].lock);
#else
  if (pthread_mutex_init(&g_mutexes[idx].lock, NULL) != 0) {
    g_mutexes[idx].used = false;
    return 0;
  }
#endif
  return mid;
}

uintptr_t astra_mutex_lock(uintptr_t mid, uintptr_t owner_tid) {
  (void)owner_tid;
  size_t idx = (size_t)mid;
  if (idx >= g_mutexes_cap || !g_mutexes[idx].used) {
    return (uintptr_t)-1;
  }
#if defined(_WIN32)
  AcquireSRWLockExclusive(&g_mutexes[idx].lock);
  return 0;
#else
  return pthread_mutex_lock(&g_mutexes[idx].lock) == 0 ? 0 : (uintptr_t)-1;
#endif
}

uintptr_t astra_mutex_unlock(uintptr_t mid, uintptr_t owner_tid) {
  (void)owner_tid;
  size_t idx = (size_t)mid;
  if (idx >= g_mutexes_cap || !g_mutexes[idx].used) {
    return (uintptr_t)-1;
  }
#if defined(_WIN32)
  ReleaseSRWLockExclusive(&g_mutexes[idx].lock);
  return 0;
#else
  return pthread_mutex_unlock(&g_mutexes[idx].lock) == 0 ? 0 : (uintptr_t)-1;
#endif
}

typedef struct {
  bool used;
  bool closed;
  size_t head;
  size_t len;
  size_t cap;
  uintptr_t *items;
#if defined(_WIN32)
  SRWLOCK lock;
  CONDITION_VARIABLE cv;
#else
  pthread_mutex_t lock;
  pthread_cond_t cv;
#endif
} AstraChanEntry;

static AstraChanEntry *g_chans = NULL;
static size_t g_chans_cap = 0;
static uintptr_t g_next_chan = 1;

static bool astra_chan_reserve(size_t want) {
  if (g_chans_cap >= want) {
    return true;
  }
  size_t next = g_chans_cap == 0 ? 8 : g_chans_cap * 2;
  while (next < want) {
    next *= 2;
  }
  AstraChanEntry *p = (AstraChanEntry *)realloc(g_chans, next * sizeof(AstraChanEntry));
  if (p == NULL) {
    return false;
  }
  for (size_t i = g_chans_cap; i < next; i++) {
    p[i].used = false;
    p[i].closed = false;
    p[i].head = 0;
    p[i].len = 0;
    p[i].cap = 0;
    p[i].items = NULL;
  }
  g_chans = p;
  g_chans_cap = next;
  return true;
}

static bool astra_chan_push(AstraChanEntry *ch, uintptr_t v) {
  if (ch->len >= ch->cap) {
    size_t next = ch->cap == 0 ? 8 : ch->cap * 2;
    uintptr_t *p = (uintptr_t *)realloc(ch->items, next * sizeof(uintptr_t));
    if (p == NULL) {
      return false;
    }
    ch->items = p;
    ch->cap = next;
  }
  ch->items[ch->len++] = v;
  return true;
}

static uintptr_t astra_chan_pop(AstraChanEntry *ch) {
  if (ch->head >= ch->len) {
    return astra_any_box_none();
  }
  uintptr_t out = ch->items[ch->head++];
  if (ch->head >= ch->len) {
    ch->head = 0;
    ch->len = 0;
  }
  return out;
}

uintptr_t astra_chan_new(void) {
  uintptr_t cid = g_next_chan++;
  size_t idx = (size_t)cid;
  if (!astra_chan_reserve(idx + 1)) {
    return 0;
  }
  AstraChanEntry *ch = &g_chans[idx];
  ch->used = true;
  ch->closed = false;
  ch->head = 0;
  ch->len = 0;
#if defined(_WIN32)
  InitializeSRWLock(&ch->lock);
  InitializeConditionVariable(&ch->cv);
#else
  if (pthread_mutex_init(&ch->lock, NULL) != 0) {
    ch->used = false;
    return 0;
  }
  if (pthread_cond_init(&ch->cv, NULL) != 0) {
    ch->used = false;
    return 0;
  }
#endif
  return cid;
}

uintptr_t astra_chan_send(uintptr_t cid, uintptr_t value) {
  size_t idx = (size_t)cid;
  if (idx >= g_chans_cap || !g_chans[idx].used) {
    return 1;
  }
  AstraChanEntry *ch = &g_chans[idx];
#if defined(_WIN32)
  AcquireSRWLockExclusive(&ch->lock);
  if (ch->closed) {
    ReleaseSRWLockExclusive(&ch->lock);
    return 1;
  }
  bool ok = astra_chan_push(ch, value);
  WakeConditionVariable(&ch->cv);
  ReleaseSRWLockExclusive(&ch->lock);
  return ok ? 0 : 1;
#else
  if (pthread_mutex_lock(&ch->lock) != 0) {
    return 1;
  }
  if (ch->closed) {
    (void)pthread_mutex_unlock(&ch->lock);
    return 1;
  }
  bool ok = astra_chan_push(ch, value);
  (void)pthread_cond_signal(&ch->cv);
  (void)pthread_mutex_unlock(&ch->lock);
  return ok ? 0 : 1;
#endif
}

uintptr_t astra_chan_recv_try(uintptr_t cid) {
  size_t idx = (size_t)cid;
  if (idx >= g_chans_cap || !g_chans[idx].used) {
    return astra_any_box_none();
  }
  AstraChanEntry *ch = &g_chans[idx];
#if defined(_WIN32)
  AcquireSRWLockExclusive(&ch->lock);
  uintptr_t out = astra_chan_pop(ch);
  ReleaseSRWLockExclusive(&ch->lock);
  return out;
#else
  if (pthread_mutex_lock(&ch->lock) != 0) {
    return astra_any_box_none();
  }
  uintptr_t out = astra_chan_pop(ch);
  (void)pthread_mutex_unlock(&ch->lock);
  return out;
#endif
}

uintptr_t astra_chan_recv_blocking(uintptr_t cid) {
  size_t idx = (size_t)cid;
  if (idx >= g_chans_cap || !g_chans[idx].used) {
    return astra_any_box_none();
  }
  AstraChanEntry *ch = &g_chans[idx];
#if defined(_WIN32)
  AcquireSRWLockExclusive(&ch->lock);
  while (ch->head >= ch->len && !ch->closed) {
    SleepConditionVariableSRW(&ch->cv, &ch->lock, INFINITE, 0);
  }
  uintptr_t out = astra_chan_pop(ch);
  ReleaseSRWLockExclusive(&ch->lock);
  return out;
#else
  if (pthread_mutex_lock(&ch->lock) != 0) {
    return astra_any_box_none();
  }
  while (ch->head >= ch->len && !ch->closed) {
    (void)pthread_cond_wait(&ch->cv, &ch->lock);
  }
  uintptr_t out = astra_chan_pop(ch);
  (void)pthread_mutex_unlock(&ch->lock);
  return out;
#endif
}

uintptr_t astra_chan_close(uintptr_t cid) {
  size_t idx = (size_t)cid;
  if (idx >= g_chans_cap || !g_chans[idx].used) {
    return 1;
  }
  AstraChanEntry *ch = &g_chans[idx];
#if defined(_WIN32)
  AcquireSRWLockExclusive(&ch->lock);
  ch->closed = true;
  WakeAllConditionVariable(&ch->cv);
  ReleaseSRWLockExclusive(&ch->lock);
  return 0;
#else
  if (pthread_mutex_lock(&ch->lock) != 0) {
    return 1;
  }
  ch->closed = true;
  (void)pthread_cond_broadcast(&ch->cv);
  (void)pthread_mutex_unlock(&ch->lock);
  return 0;
#endif
}

_Bool astra_file_exists(uintptr_t path_ptr) {
  const char *path = (const char *)path_ptr;
  if (path == NULL) {
    return 0;
  }
#if defined(_WIN32)
  return _access(path, 0) == 0;
#else
  return access(path, F_OK) == 0;
#endif
}

uintptr_t astra_file_remove(uintptr_t path_ptr) {
  const char *path = (const char *)path_ptr;
  if (path == NULL) {
    return (uintptr_t)-1;
  }
  return remove(path) == 0 ? 0 : (uintptr_t)-1;
}

typedef struct {
  uintptr_t fd;
  bool used;
} SocketEntry;

static SocketEntry *g_sockets = NULL;
static size_t g_sockets_cap = 0;
static uintptr_t g_next_sid = 1;

static bool astra_socket_reserve(size_t want) {
  if (g_sockets_cap >= want) {
    return true;
  }
  size_t next = g_sockets_cap == 0 ? 8 : g_sockets_cap * 2;
  while (next < want) {
    next *= 2;
  }
  SocketEntry *p = (SocketEntry *)realloc(g_sockets, next * sizeof(SocketEntry));
  if (p == NULL) {
    return false;
  }
  for (size_t i = g_sockets_cap; i < next; i++) {
    p[i].fd = 0;
    p[i].used = false;
  }
  g_sockets = p;
  g_sockets_cap = next;
  return true;
}

static uintptr_t astra_socket_fd(uintptr_t sid) {
  size_t idx = (size_t)sid;
  if (idx >= g_sockets_cap || !g_sockets[idx].used) {
    return 0;
  }
  return g_sockets[idx].fd;
}

#if defined(_WIN32)
static bool astra_net_ready = false;

static bool astra_socket_init(void) {
  if (astra_net_ready) {
    return true;
  }
  WSADATA wsa;
  if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
    return false;
  }
  astra_net_ready = true;
  return true;
}
#endif

static char *astra_dup_slice(const char *src, size_t n) {
  char *out = (char *)malloc(n + 1);
  if (out == NULL) {
    return NULL;
  }
  memcpy(out, src, n);
  out[n] = '\0';
  return out;
}

static bool astra_split_host_port(const char *addr, char **host_out, char **port_out) {
  if (addr == NULL || host_out == NULL || port_out == NULL) {
    return false;
  }
  *host_out = NULL;
  *port_out = NULL;

  const char *host_start = addr;
  const char *host_end = NULL;
  const char *port_start = NULL;

  if (addr[0] == '[') {
    const char *close = strchr(addr, ']');
    if (close == NULL || close[1] != ':') {
      return false;
    }
    host_start = addr + 1;
    host_end = close;
    port_start = close + 2;
  } else {
    const char *sep = strrchr(addr, ':');
    if (sep == NULL) {
      return false;
    }
    host_end = sep;
    port_start = sep + 1;
  }

  if (host_end <= host_start || port_start[0] == '\0') {
    return false;
  }

  size_t host_len = (size_t)(host_end - host_start);
  size_t port_len = strlen(port_start);
  char *host = astra_dup_slice(host_start, host_len);
  char *port = astra_dup_slice(port_start, port_len);
  if (host == NULL || port == NULL) {
    free(host);
    free(port);
    return false;
  }
  *host_out = host;
  *port_out = port;
  return true;
}

uintptr_t astra_tcp_connect(uintptr_t addr_ptr) {
#if defined(_WIN32)
  const char *addr = (const char *)addr_ptr;
  char *host = NULL;
  char *port = NULL;
  if (!astra_split_host_port(addr, &host, &port)) {
    return (uintptr_t)-1;
  }
  if (!astra_socket_init()) {
    free(host);
    free(port);
    return (uintptr_t)-1;
  }

  struct addrinfo hints;
  memset(&hints, 0, sizeof(hints));
  hints.ai_family = AF_UNSPEC;
  hints.ai_socktype = SOCK_STREAM;

  struct addrinfo *res = NULL;
  int gai = getaddrinfo(host, port, &hints, &res);
  free(host);
  free(port);
  if (gai != 0 || res == NULL) {
    if (res != NULL) {
      freeaddrinfo(res);
    }
    return (uintptr_t)-1;
  }

  SOCKET fd = INVALID_SOCKET;
  for (struct addrinfo *it = res; it != NULL; it = it->ai_next) {
    fd = socket(it->ai_family, it->ai_socktype, it->ai_protocol);
    if (fd == INVALID_SOCKET) {
      continue;
    }
    if (connect(fd, it->ai_addr, (int)it->ai_addrlen) == 0) {
      break;
    }
    closesocket(fd);
    fd = INVALID_SOCKET;
  }
  freeaddrinfo(res);
  if (fd == INVALID_SOCKET) {
    return (uintptr_t)-1;
  }

  uintptr_t sid = g_next_sid++;
  size_t idx = (size_t)sid;
  if (!astra_socket_reserve(idx + 1)) {
    closesocket(fd);
    return (uintptr_t)-1;
  }
  g_sockets[idx].fd = (uintptr_t)fd;
  g_sockets[idx].used = true;
  return sid;
#else
  const char *addr = (const char *)addr_ptr;
  char *host = NULL;
  char *port = NULL;
  if (!astra_split_host_port(addr, &host, &port)) {
    return (uintptr_t)-1;
  }

  struct addrinfo hints;
  memset(&hints, 0, sizeof(hints));
  hints.ai_family = AF_UNSPEC;
  hints.ai_socktype = SOCK_STREAM;

  struct addrinfo *res = NULL;
  int gai = getaddrinfo(host, port, &hints, &res);
  free(host);
  free(port);
  if (gai != 0 || res == NULL) {
    if (res != NULL) {
      freeaddrinfo(res);
    }
    return (uintptr_t)-1;
  }

  int fd = -1;
  for (struct addrinfo *it = res; it != NULL; it = it->ai_next) {
    fd = socket(it->ai_family, it->ai_socktype, it->ai_protocol);
    if (fd < 0) {
      continue;
    }
    if (connect(fd, it->ai_addr, it->ai_addrlen) == 0) {
      break;
    }
    close(fd);
    fd = -1;
  }
  freeaddrinfo(res);
  if (fd < 0) {
    return (uintptr_t)-1;
  }

  uintptr_t sid = g_next_sid++;
  size_t idx = (size_t)sid;
  if (!astra_socket_reserve(idx + 1)) {
    close(fd);
    return (uintptr_t)-1;
  }
  g_sockets[idx].fd = (uintptr_t)fd;
  g_sockets[idx].used = true;
  return sid;
#endif
}

uintptr_t astra_tcp_send(uintptr_t sid, uintptr_t data_ptr) {
#if defined(_WIN32)
  SOCKET fd = (SOCKET)astra_socket_fd(sid);
  const char *data = (const char *)data_ptr;
  if (fd == INVALID_SOCKET || data == NULL) {
    return (uintptr_t)-1;
  }
  size_t len = strlen(data);
  if (len == 0) {
    return 0;
  }
  int sent = send(fd, data, (int)len, 0);
  if (sent == SOCKET_ERROR) {
    return (uintptr_t)-1;
  }
  return (uintptr_t)sent;
#else
  int fd = (int)astra_socket_fd(sid);
  const char *data = (const char *)data_ptr;
  if (fd < 0 || data == NULL) {
    return (uintptr_t)-1;
  }
  size_t len = strlen(data);
  if (len == 0) {
    return 0;
  }
  ssize_t sent = send(fd, data, len, 0);
  if (sent < 0) {
    return (uintptr_t)-1;
  }
  return (uintptr_t)sent;
#endif
}

uintptr_t astra_tcp_recv(uintptr_t sid, uintptr_t n) {
#if defined(_WIN32)
  SOCKET fd = (SOCKET)astra_socket_fd(sid);
  if (fd == INVALID_SOCKET) {
    return (uintptr_t)astra_strdup_s("");
  }
  size_t want = (size_t)n;
  if (want == 0) {
    want = 1;
  }
  char *buf = (char *)astra_heap_alloc(want + 1);
  if (buf == NULL) {
    return (uintptr_t)astra_strdup_s("");
  }
  int got = recv(fd, buf, (int)want, 0);
  if (got <= 0) {
    buf[0] = '\0';
    return (uintptr_t)buf;
  }
  buf[(size_t)got] = '\0';
  return (uintptr_t)buf;
#else
  int fd = (int)astra_socket_fd(sid);
  if (fd < 0) {
    return (uintptr_t)astra_strdup_s("");
  }
  size_t want = (size_t)n;
  if (want == 0) {
    want = 1;
  }
  char *buf = (char *)astra_heap_alloc(want + 1);
  if (buf == NULL) {
    return (uintptr_t)astra_strdup_s("");
  }
  ssize_t got = recv(fd, buf, want, 0);
  if (got <= 0) {
    buf[0] = '\0';
    return (uintptr_t)buf;
  }
  buf[(size_t)got] = '\0';
  return (uintptr_t)buf;
#endif
}

uintptr_t astra_tcp_close(uintptr_t sid) {
#if defined(_WIN32)
  size_t idx = (size_t)sid;
  if (idx >= g_sockets_cap || !g_sockets[idx].used) {
    return 0;
  }
  SOCKET fd = (SOCKET)g_sockets[idx].fd;
  g_sockets[idx].fd = 0;
  g_sockets[idx].used = false;
  if (fd == INVALID_SOCKET) {
    return 0;
  }
  return closesocket(fd) == 0 ? 0 : (uintptr_t)-1;
#else
  size_t idx = (size_t)sid;
  if (idx >= g_sockets_cap || !g_sockets[idx].used) {
    return 0;
  }
  int fd = (int)g_sockets[idx].fd;
  g_sockets[idx].fd = 0;
  g_sockets[idx].used = false;
  if (fd < 0) {
    return 0;
  }
  return close(fd) == 0 ? 0 : (uintptr_t)-1;
#endif
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

uintptr_t astra_rand_bytes(uintptr_t n) {
  if ((int64_t)n < 0) {
    return astra_any_box_none();
  }
  size_t len = (size_t)n;
  uintptr_t out = astra_list_new();
  if (out == 0) {
    return astra_any_box_none();
  }
  if (len == 0) {
    return out;
  }
  unsigned char *buf = (unsigned char *)malloc(len);
  if (buf == NULL) {
    return astra_any_box_none();
  }
#if defined(_WIN32)
  NTSTATUS st = BCryptGenRandom(NULL, buf, (ULONG)len, BCRYPT_USE_SYSTEM_PREFERRED_RNG);
  if (st < 0) {
    free(buf);
    return astra_any_box_none();
  }
#else
  FILE *rng = fopen("/dev/urandom", "rb");
  if (rng == NULL) {
    free(buf);
    return astra_any_box_none();
  }
  size_t got = fread(buf, 1, len, rng);
  fclose(rng);
  if (got != len) {
    free(buf);
    return astra_any_box_none();
  }
#endif
  for (size_t i = 0; i < len; i++) {
    (void)astra_list_push(out, astra_any_box_i64((int64_t)buf[i]));
  }
  free(buf);
  return out;
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
#if defined(_WIN32)
  if (_getcwd(buf, (int)sizeof(buf)) == NULL) {
    return (uintptr_t)astra_strdup_s("");
  }
#else
  if (getcwd(buf, sizeof(buf)) == NULL) {
    return (uintptr_t)astra_strdup_s("");
  }
#endif
  return (uintptr_t)astra_strdup_s(buf);
}

uintptr_t astra_proc_run(uintptr_t cmd_ptr) {
  const char *cmd = (const char *)cmd_ptr;
  if (cmd == NULL) {
    return (uintptr_t)-1;
  }
  int rc = system(cmd);
  if (rc < 0) {
    return (uintptr_t)-1;
  }
#if defined(_WIN32)
  return (uintptr_t)rc;
#else
  if (WIFEXITED(rc)) {
    return (uintptr_t)WEXITSTATUS(rc);
  }
  if (WIFSIGNALED(rc)) {
    return (uintptr_t)(128 + WTERMSIG(rc));
  }
  return (uintptr_t)rc;
#endif
}

uintptr_t astra_now_unix(void) {
  return (uintptr_t)time(NULL);
}

uintptr_t astra_monotonic_ms(void) {
#if defined(_WIN32)
  return (uintptr_t)GetTickCount64();
#else
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
#endif
}

uintptr_t astra_sleep_ms(uintptr_t ms) {
#if defined(_WIN32)
  DWORD wait_ms = (DWORD)((uint64_t)ms > (uint64_t)0xFFFFFFFFULL ? 0xFFFFFFFFUL : (DWORD)ms);
  Sleep(wait_ms);
  return 0;
#else
  struct timespec ts;
  uint64_t v = (uint64_t)ms;
  ts.tv_sec = (time_t)(v / 1000ULL);
  ts.tv_nsec = (long)((v % 1000ULL) * 1000000ULL);
  while (nanosleep(&ts, &ts) != 0 && errno == EINTR) {
  }
  return 0;
#endif
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
