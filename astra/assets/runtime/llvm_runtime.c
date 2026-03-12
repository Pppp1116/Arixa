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
#include <direct.h>
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

#if !defined(NDEBUG) || defined(ASTRA_ENABLE_ANY_RUNTIME)
// Forward declaration
static void astra_trap(void);

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
#else
// In release builds (NDEBUG defined), disable allocation tracking
#define astra_track_ptr(p) ((void)0)
#define astra_untrack_ptr(p) ((void)0)
#endif

#if defined(ASTRA_ENABLE_ANY_RUNTIME)
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
  AstraAnyTag tag;
  union {
    int64_t i64;
    double f64;
    uintptr_t ptr;
    _Bool b;
  } value;
  uint32_t generation;  // Generation counter for handle validation
  bool live;            // Whether this slot is in use
} AstraAnySlot;

typedef struct {
  AstraAnySlot *slots;
  size_t capacity;
  size_t next_free;     // Index of next free slot to try
  uint32_t next_generation;
} AstraAnySlotTable;

static AstraAnySlotTable g_any_table = {NULL, 0, 0, 1};

static bool astra_any_table_reserve(size_t min_capacity) {
  if (g_any_table.capacity >= min_capacity) {
    return true;
  }
  size_t next = g_any_table.capacity == 0 ? 16 : g_any_table.capacity * 2;
  while (next < min_capacity) {
    next *= 2;
  }
  AstraAnySlot *p = (AstraAnySlot *)realloc(g_any_table.slots, next * sizeof(AstraAnySlot));
  if (p == NULL) {
    return false;
  }
  // Initialize new slots
  for (size_t i = g_any_table.capacity; i < next; i++) {
    p[i].live = false;
    p[i].generation = 0;
  }
  g_any_table.slots = p;
  g_any_table.capacity = next;
  return true;
}

static uintptr_t astra_any_alloc_slot(AstraAnyTag tag) {
  if (!astra_any_table_reserve(g_any_table.next_free + 1)) {
    return 0;
  }
  
  // Find the next available slot
  size_t start = g_any_table.next_free;
  for (size_t i = start; i < g_any_table.capacity; i++) {
    if (!g_any_table.slots[i].live) {
      g_any_table.slots[i].live = true;
      g_any_table.slots[i].tag = tag;
      g_any_table.slots[i].generation = g_any_table.next_generation++;
      g_any_table.slots[i].value.ptr = 0;
      g_any_table.next_free = i + 1;
      
      // Pack slot index and generation into handle
      uintptr_t handle = ((uintptr_t)g_any_table.slots[i].generation << 32) | (uintptr_t)i;
      return handle;
    }
  }
  
  // If we didn't find one, wrap around and check from beginning
  for (size_t i = 0; i < start; i++) {
    if (!g_any_table.slots[i].live) {
      g_any_table.slots[i].live = true;
      g_any_table.slots[i].tag = tag;
      g_any_table.slots[i].generation = g_any_table.next_generation++;
      g_any_table.slots[i].value.ptr = 0;
      g_any_table.next_free = i + 1;
      
      uintptr_t handle = ((uintptr_t)g_any_table.slots[i].generation << 32) | (uintptr_t)i;
      return handle;
    }
  }
  
  // No free slots available
  return 0;
}

static AstraAnySlot *astra_any_find_slot(uintptr_t handle) {
  size_t slot_index = (size_t)(handle & 0xFFFFFFFF);
  uint32_t generation = (uint32_t)(handle >> 32);
  
  if (slot_index >= g_any_table.capacity) {
    return NULL;
  }
  
  AstraAnySlot *slot = &g_any_table.slots[slot_index];
  if (!slot->live || slot->generation != generation) {
    return NULL;
  }
  
  return slot;
}

static void astra_any_free_slot(uintptr_t handle) {
  size_t slot_index = (size_t)(handle & 0xFFFFFFFF);
  uint32_t generation = (uint32_t)(handle >> 32);
  
  if (slot_index >= g_any_table.capacity) {
    return;
  }
  
  AstraAnySlot *slot = &g_any_table.slots[slot_index];
  if (slot->live && slot->generation == generation) {
    slot->live = false;
    slot->generation = 0;
    if (slot_index < g_any_table.next_free) {
      g_any_table.next_free = slot_index;
    }
  }
}

static AstraAnySlot *astra_any_expect(uintptr_t handle) {
  AstraAnySlot *slot = astra_any_find_slot(handle);
  if (slot == NULL) {
    astra_trap();
  }
  return slot;
}

// Hash function for Any values (for dynamic maps)
static uint64_t astra_hash_any(uintptr_t any_value) {
  AstraAnySlot *slot = astra_any_find_slot(any_value);
  if (slot == NULL) return 0;
  
  uint64_t hash = 14695981039346656037ULL;
  
  switch (slot->tag) {
  case ASTRA_ANY_INT:
    // Hash the int64 value directly
    for (int i = 0; i < 8; i++) {
      hash ^= ((uint8_t *)&slot->value.i64)[i];
      hash *= 1099511628211ULL;
    }
    break;
  case ASTRA_ANY_STR: {
    // Hash the string content
    const char *str = (const char *)slot->value.ptr;
    if (str) {
      for (size_t i = 0; str[i]; i++) {
        hash ^= (uint8_t)str[i];
        hash *= 1099511628211ULL;
      }
    }
    break;
  }
  default:
    // For other types, hash the handle value
    for (int i = 0; i < 8; i++) {
      hash ^= ((uint8_t *)&any_value)[i];
      hash *= 1099511628211ULL;
    }
    break;
  }
  
  return hash;
}
#endif

static void *astra_heap_alloc(size_t n) {
  size_t want = n == 0 ? 1 : n;
  void *p = malloc(want);
#if !defined(NDEBUG) || defined(ASTRA_ENABLE_ANY_RUNTIME)
  astra_track_ptr(p);
#endif
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
#if !defined(NDEBUG) || defined(ASTRA_ENABLE_ANY_RUNTIME)
  astra_track_ptr(p);
#endif
  return (uintptr_t)p;
}

void astra_free(uintptr_t ptr, uintptr_t size, uintptr_t align) {
  (void)size;
  (void)align;
  if (ptr != 0) {
    void *p = (void *)ptr;
#if !defined(NDEBUG) || defined(ASTRA_ENABLE_ANY_RUNTIME)
    astra_untrack_ptr(p);
#endif
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

// Hash table entry for dynamic Any maps
typedef struct {
  uint64_t hash;
  uintptr_t key;
  uintptr_t value;
  bool occupied;
} AnyMapEntry;

typedef struct {
  AnyMapEntry *entries;
  size_t capacity;
  size_t size;
  size_t mask;  // capacity - 1, for fast modulo
} AstraAnyMap;

// Typed collections for fast native operations
typedef struct {
  size_t len;
  size_t cap;
  int64_t *items;  // Direct storage for Int vectors
} AstraIntVector;

typedef struct {
  size_t len;
  size_t cap;
  double *items;  // Direct storage for Float vectors
} AstraFloatVector;

typedef struct {
  size_t len;
  size_t cap;
  char **items;  // Direct storage for String vectors
} AstraStringVector;

// Hash table entry for typed maps
typedef struct {
  uint64_t hash;
  int64_t key;
  int64_t value;
  bool occupied;
} IntMapEntry;

typedef struct {
  IntMapEntry *entries;
  size_t capacity;
  size_t size;
  size_t mask;  // capacity - 1, for fast modulo
} AstraIntMap;

// Simple hash function for int64_t keys
static uint64_t astra_hash_int64(int64_t key) {
  // Use FNV-1a hash on the bytes of the int64_t
  uint64_t hash = 14695981039346656037ULL;
  uint8_t *bytes = (uint8_t *)&key;
  for (int i = 0; i < 8; i++) {
    hash ^= bytes[i];
    hash *= 1099511628211ULL;
  }
  return hash;
}

// Find next power of 2 for hash table sizing
static size_t astra_next_pow2(size_t n) {
  if (n <= 1) return 2;
  n--;
  n |= n >> 1;
  n |= n >> 2;
  n |= n >> 4;
  n |= n >> 8;
  n |= n >> 16;
  n |= n >> 32;
  return n + 1;
}

typedef struct {
  int kind;
  void *ptr;
  uint32_t generation;  // Generation counter for handle validation
  bool live;            // Whether this slot is in use
} ObjSlot;

typedef struct {
  ObjSlot *slots;
  size_t capacity;
  size_t next_free;     // Index of next free slot to try
  uint32_t next_generation;
} ObjSlotTable;

static ObjSlotTable g_obj_table = {NULL, 0, 0, 1};

enum {
  OBJ_KIND_LIST = 1,
  OBJ_KIND_MAP = 2,
};

static bool astra_obj_table_reserve(size_t min_capacity) {
  if (g_obj_table.capacity >= min_capacity) {
    return true;
  }
  size_t next = g_obj_table.capacity == 0 ? 8 : g_obj_table.capacity * 2;
  while (next < min_capacity) {
    next *= 2;
  }
  ObjSlot *p = (ObjSlot *)realloc(g_obj_table.slots, next * sizeof(ObjSlot));
  if (p == NULL) {
    return false;
  }
  // Initialize new slots
  for (size_t i = g_obj_table.capacity; i < next; i++) {
    p[i].live = false;
    p[i].generation = 0;
  }
  g_obj_table.slots = p;
  g_obj_table.capacity = next;
  return true;
}

static uintptr_t astra_obj_add_slot(int kind, void *ptr) {
  if (!astra_obj_table_reserve(g_obj_table.next_free + 1)) {
    return 0;
  }
  
  // Find the next available slot
  size_t start = g_obj_table.next_free;
  for (size_t i = start; i < g_obj_table.capacity; i++) {
    if (!g_obj_table.slots[i].live) {
      g_obj_table.slots[i].live = true;
      g_obj_table.slots[i].kind = kind;
      g_obj_table.slots[i].ptr = ptr;
      g_obj_table.slots[i].generation = g_obj_table.next_generation++;
      g_obj_table.next_free = i + 1;
      
      // Pack slot index and generation into handle
      uintptr_t handle = ((uintptr_t)g_obj_table.slots[i].generation << 32) | (uintptr_t)i;
      return handle;
    }
  }
  
  // If we didn't find one, wrap around and check from beginning
  for (size_t i = 0; i < start; i++) {
    if (!g_obj_table.slots[i].live) {
      g_obj_table.slots[i].live = true;
      g_obj_table.slots[i].kind = kind;
      g_obj_table.slots[i].ptr = ptr;
      g_obj_table.slots[i].generation = g_obj_table.next_generation++;
      g_obj_table.next_free = i + 1;
      
      uintptr_t handle = ((uintptr_t)g_obj_table.slots[i].generation << 32) | (uintptr_t)i;
      return handle;
    }
  }
  
  // No free slots available
  return 0;
}

static ObjSlot *astra_obj_find_slot(uintptr_t handle) {
  size_t slot_index = (size_t)(handle & 0xFFFFFFFF);
  uint32_t generation = (uint32_t)(handle >> 32);
  
  if (slot_index >= g_obj_table.capacity) {
    return NULL;
  }
  
  ObjSlot *slot = &g_obj_table.slots[slot_index];
  if (!slot->live || slot->generation != generation) {
    return NULL;
  }
  
  return slot;
}

static void astra_obj_free_slot(uintptr_t handle) {
  size_t slot_index = (size_t)(handle & 0xFFFFFFFF);
  uint32_t generation = (uint32_t)(handle >> 32);
  
  if (slot_index >= g_obj_table.capacity) {
    return;
  }
  
  ObjSlot *slot = &g_obj_table.slots[slot_index];
  if (slot->live && slot->generation == generation) {
    slot->live = false;
    slot->generation = 0;
    if (slot_index < g_obj_table.next_free) {
      g_obj_table.next_free = slot_index;
    }
  }
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

#if defined(ASTRA_ENABLE_ANY_RUNTIME)
uintptr_t astra_any_box_i64(int64_t value) {
  uintptr_t h = astra_any_alloc_slot(ASTRA_ANY_INT);
  if (h == 0) {
    return 0;
  }
  AstraAnySlot *slot = astra_any_expect(h);
  slot->value.i64 = value;
  return h;
}

uintptr_t astra_any_box_bool(_Bool value) {
  uintptr_t h = astra_any_alloc_slot(ASTRA_ANY_BOOL);
  if (h == 0) {
    return 0;
  }
  AstraAnySlot *slot = astra_any_expect(h);
  slot->value.b = value ? 1 : 0;
  return h;
}

uintptr_t astra_any_box_f64(double value) {
  uintptr_t h = astra_any_alloc_slot(ASTRA_ANY_FLOAT);
  if (h == 0) {
    return 0;
  }
  AstraAnySlot *slot = astra_any_expect(h);
  slot->value.f64 = value;
  return h;
}

uintptr_t astra_any_box_str(uintptr_t value) {
  uintptr_t h = astra_any_alloc_slot(ASTRA_ANY_STR);
  if (h == 0) {
    return 0;
  }
  AstraAnySlot *entry = astra_any_expect(h);
  entry->value.ptr = value;
  return h;
}

uintptr_t astra_any_box_ptr(uintptr_t value) {
  uintptr_t h = astra_any_alloc_slot(ASTRA_ANY_PTR);
  if (h == 0) {
    return 0;
  }
  AstraAnySlot *entry = astra_any_expect(h);
  entry->value.ptr = value;
  return h;
}

static uintptr_t astra_any_box_obj(AstraAnyTag tag, uintptr_t handle) {
  uintptr_t h = astra_any_alloc_slot(tag);
  if (h == 0) {
    return 0;
  }
  AstraAnySlot *entry = astra_any_expect(h);
  entry->value.ptr = handle;
  return h;
}

uintptr_t astra_any_box_none(void) {
  uintptr_t h = astra_any_alloc_slot(ASTRA_ANY_NONE);
  if (h == 0) {
    return 0;
  }
  AstraAnySlot *entry = astra_any_expect(h);
  entry->value.ptr = 0;
  return h;
}

int64_t astra_any_to_i64(uintptr_t value) {
  AstraAnySlot *entry = astra_any_expect(value);
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
  AstraAnySlot *entry = astra_any_expect(value);
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
  AstraAnySlot *entry = astra_any_expect(value);
  return entry->tag == ASTRA_ANY_NONE ? 1 : 0;
}

double astra_any_to_f64(uintptr_t value) {
  AstraAnySlot *entry = astra_any_expect(value);
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

uintptr_t astra_to_json(uintptr_t v);

uintptr_t astra_any_to_str(uintptr_t value) {
  AstraAnySlot *entry = astra_any_expect(value);
  if (entry->tag == ASTRA_ANY_STR) {
    return entry->value.ptr;
  }
  astra_trap();
  return 0;
}

uintptr_t astra_any_to_display(uintptr_t value) {
  AstraAnySlot *entry = astra_any_find_slot(value);
  if (entry == NULL) {
    return (uintptr_t)astra_strdup_s("none");
  }
  char num[64];
  switch (entry->tag) {
  case ASTRA_ANY_NONE:
    return (uintptr_t)astra_strdup_s("none");
  case ASTRA_ANY_INT:
    (void)snprintf(num, sizeof(num), "%lld", (long long)entry->value.i64);
    return (uintptr_t)astra_strdup_s(num);
  case ASTRA_ANY_BOOL:
    return (uintptr_t)astra_strdup_s(entry->value.b ? "true" : "false");
  case ASTRA_ANY_FLOAT:
    if (isnan(entry->value.f64)) {
      return (uintptr_t)astra_strdup_s("nan");
    }
    if (isinf(entry->value.f64)) {
      return (uintptr_t)astra_strdup_s(entry->value.f64 > 0.0 ? "inf" : "-inf");
    }
    (void)snprintf(num, sizeof(num), "%.15g", entry->value.f64);
    return (uintptr_t)astra_strdup_s(num);
  case ASTRA_ANY_STR:
    return (uintptr_t)astra_strdup_s((const char *)entry->value.ptr);
  case ASTRA_ANY_PTR:
    (void)snprintf(num, sizeof(num), "%llu", (unsigned long long)entry->value.ptr);
    return (uintptr_t)astra_strdup_s(num);
  case ASTRA_ANY_LIST:
  case ASTRA_ANY_MAP:
    return astra_to_json(value);
  default:
    return (uintptr_t)astra_strdup_s("none");
  }
}

uintptr_t astra_any_to_ptr(uintptr_t value) {
  AstraAnySlot *entry = astra_any_expect(value);
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
  AstraAnySlot *ea = astra_any_find_slot(a);
  AstraAnySlot *eb = astra_any_find_slot(b);
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
  AstraAnySlot *any = astra_any_expect(list_any);
  if (any->tag != ASTRA_ANY_LIST) {
    astra_trap();
  }
  ObjSlot *slot = astra_obj_find_slot(any->value.ptr);
  if (slot == NULL || slot->kind != OBJ_KIND_LIST) {
    astra_trap();
  }
  return (AstraList *)slot->ptr;
}

static AstraMap *astra_expect_map(uintptr_t map_any) {
  AstraAnySlot *any = astra_any_expect(map_any);
  if (any->tag != ASTRA_ANY_MAP) {
    astra_trap();
  }
  ObjSlot *slot = astra_obj_find_slot(any->value.ptr);
  if (slot == NULL || slot->kind != OBJ_KIND_MAP) {
    astra_trap();
  }
  return (AstraMap *)slot->ptr;
}

uintptr_t astra_list_new(void) {
  AstraList *xs = (AstraList *)calloc(1, sizeof(AstraList));
  if (xs == NULL) {
    return 0;
  }
  uintptr_t obj_h = astra_obj_add_slot(OBJ_KIND_LIST, xs);
  if (obj_h == 0) {
    return 0;
  }
  return astra_any_box_obj(ASTRA_ANY_LIST, obj_h);
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
  uintptr_t obj_h = astra_obj_add_slot(OBJ_KIND_MAP, m);
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

// ============================================================================
// TYPED COLLECTION OPERATIONS (Fast Native Path)
// ============================================================================

// Int Vector operations
static AstraIntVector *astra_int_vector_new(size_t initial_cap) {
  AstraIntVector *vec = (AstraIntVector *)malloc(sizeof(AstraIntVector));
  if (vec == NULL) return NULL;
  
  vec->len = 0;
  vec->cap = initial_cap > 0 ? initial_cap : 8;
  vec->items = (int64_t *)malloc(vec->cap * sizeof(int64_t));
  if (vec->items == NULL) {
    free(vec);
    return NULL;
  }
  
  return vec;
}

static bool astra_int_vector_reserve(AstraIntVector *vec, size_t new_cap) {
  if (vec->cap >= new_cap) return true;
  
  size_t next = vec->cap * 2;
  while (next < new_cap) next *= 2;
  
  int64_t *new_items = (int64_t *)realloc(vec->items, next * sizeof(int64_t));
  if (new_items == NULL) return false;
  
  vec->items = new_items;
  vec->cap = next;
  return true;
}

static bool astra_int_vector_push(AstraIntVector *vec, int64_t value) {
  if (!astra_int_vector_reserve(vec, vec->len + 1)) return false;
  vec->items[vec->len++] = value;
  return true;
}

static int64_t astra_int_vector_get(AstraIntVector *vec, size_t index) {
  if (index >= vec->len) return 0;  // Bounds check
  return vec->items[index];
}

static void astra_int_vector_free(AstraIntVector *vec) {
  if (vec) {
    free(vec->items);
    free(vec);
  }
}

// Int Map operations (hash table)
static AstraIntMap *astra_int_map_new(size_t initial_cap) {
  AstraIntMap *map = (AstraIntMap *)malloc(sizeof(AstraIntMap));
  if (map == NULL) return NULL;
  
  size_t cap = astra_next_pow2(initial_cap > 0 ? initial_cap : 8);
  map->entries = (IntMapEntry *)calloc(cap, sizeof(IntMapEntry));
  if (map->entries == NULL) {
    free(map);
    return NULL;
  }
  
  map->capacity = cap;
  map->size = 0;
  map->mask = cap - 1;
  return map;
}

static IntMapEntry *astra_int_map_find_entry(AstraIntMap *map, int64_t key) {
  uint64_t hash = astra_hash_int64(key);
  size_t index = hash & map->mask;
  
  // Linear probing
  for (size_t i = 0; i < map->capacity; i++) {
    size_t pos = (index + i) & map->mask;
    IntMapEntry *entry = &map->entries[pos];
    
    if (!entry->occupied) return entry;  // Empty slot
    if (entry->hash == hash && entry->key == key) return entry;  // Found
  }
  
  return NULL;  // Table full
}

static bool astra_int_map_resize(AstraIntMap *map, size_t new_cap) {
  new_cap = astra_next_pow2(new_cap);
  
  IntMapEntry *new_entries = (IntMapEntry *)calloc(new_cap, sizeof(IntMapEntry));
  if (new_entries == NULL) return false;
  
  // Rehash all entries
  for (size_t i = 0; i < map->capacity; i++) {
    IntMapEntry *old_entry = &map->entries[i];
    if (old_entry->occupied) {
      size_t index = old_entry->hash & (new_cap - 1);
      
      for (size_t j = 0; j < new_cap; j++) {
        size_t pos = (index + j) & (new_cap - 1);
        IntMapEntry *new_entry = &new_entries[pos];
        if (!new_entry->occupied) {
          *new_entry = *old_entry;
          break;
        }
      }
    }
  }
  
  free(map->entries);
  map->entries = new_entries;
  map->capacity = new_cap;
  map->mask = new_cap - 1;
  return true;
}

static bool astra_int_map_set(AstraIntMap *map, int64_t key, int64_t value) {
  if (map->size * 2 > map->capacity) {
    if (!astra_int_map_resize(map, map->capacity * 2)) return false;
  }
  
  IntMapEntry *entry = astra_int_map_find_entry(map, key);
  if (entry == NULL) return false;  // Shouldn't happen with proper resizing
  
  if (!entry->occupied) {
    entry->hash = astra_hash_int64(key);
    entry->key = key;
    map->size++;
  }
  
  entry->value = value;
  entry->occupied = true;
  return true;
}

static bool astra_int_map_get(AstraIntMap *map, int64_t key, int64_t *out_value) {
  uint64_t hash = astra_hash_int64(key);
  size_t index = hash & map->mask;
  
  for (size_t i = 0; i < map->capacity; i++) {
    size_t pos = (index + i) & map->mask;
    IntMapEntry *entry = &map->entries[pos];
    
    if (!entry->occupied) return false;
    if (entry->hash == hash && entry->key == key) {
      *out_value = entry->value;
      return true;
    }
  }
  
  return false;
}

static bool astra_int_map_has(AstraIntMap *map, int64_t key) {
  int64_t dummy;
  return astra_int_map_get(map, key, &dummy);
}

static void astra_int_map_free(AstraIntMap *map) {
  if (map) {
    free(map->entries);
    free(map);
  }
}

#if defined(ASTRA_ENABLE_ANY_RUNTIME)
// ============================================================================
// OPTIMIZED DYNAMIC COLLECTION OPERATIONS (Hash Tables)
// ============================================================================

// Optimized dynamic map operations using hash tables
static AstraAnyMap *astra_any_map_new(size_t initial_cap) {
  AstraAnyMap *map = (AstraAnyMap *)malloc(sizeof(AstraAnyMap));
  if (map == NULL) return NULL;
  
  size_t cap = astra_next_pow2(initial_cap > 0 ? initial_cap : 8);
  map->entries = (AnyMapEntry *)calloc(cap, sizeof(AnyMapEntry));
  if (map->entries == NULL) {
    free(map);
    return NULL;
  }
  
  map->capacity = cap;
  map->size = 0;
  map->mask = cap - 1;
  return map;
}

static AnyMapEntry *astra_any_map_find_entry(AstraAnyMap *map, uintptr_t key) {
  uint64_t hash = astra_hash_any(key);
  size_t index = hash & map->mask;
  
  // Linear probing
  for (size_t i = 0; i < map->capacity; i++) {
    size_t pos = (index + i) & map->mask;
    AnyMapEntry *entry = &map->entries[pos];
    
    if (!entry->occupied) return entry;  // Empty slot
    if (entry->hash == hash && astra_any_equal(entry->key, key)) return entry;  // Found
  }
  
  return NULL;  // Table full
}

static bool astra_any_map_resize(AstraAnyMap *map, size_t new_cap) {
  new_cap = astra_next_pow2(new_cap);
  
  AnyMapEntry *new_entries = (AnyMapEntry *)calloc(new_cap, sizeof(AnyMapEntry));
  if (new_entries == NULL) return false;
  
  // Rehash all entries
  for (size_t i = 0; i < map->capacity; i++) {
    AnyMapEntry *old_entry = &map->entries[i];
    if (old_entry->occupied) {
      size_t index = old_entry->hash & (new_cap - 1);
      
      for (size_t j = 0; j < new_cap; j++) {
        size_t pos = (index + j) & (new_cap - 1);
        AnyMapEntry *new_entry = &new_entries[pos];
        if (!new_entry->occupied) {
          *new_entry = *old_entry;
          break;
        }
      }
    }
  }
  
  free(map->entries);
  map->entries = new_entries;
  map->capacity = new_cap;
  map->mask = new_cap - 1;
  return true;
}

static bool astra_any_map_set(AstraAnyMap *map, uintptr_t key, uintptr_t value) {
  if (map->size * 2 > map->capacity) {
    if (!astra_any_map_resize(map, map->capacity * 2)) return false;
  }
  
  AnyMapEntry *entry = astra_any_map_find_entry(map, key);
  if (entry == NULL) return false;  // Shouldn't happen with proper resizing
  
  if (!entry->occupied) {
    entry->hash = astra_hash_any(key);
    entry->key = key;
    map->size++;
  }
  
  entry->value = value;
  entry->occupied = true;
  return true;
}

static bool astra_any_map_get(AstraAnyMap *map, uintptr_t key, uintptr_t *out_value) {
  uint64_t hash = astra_hash_any(key);
  size_t index = hash & map->mask;
  
  for (size_t i = 0; i < map->capacity; i++) {
    size_t pos = (index + i) & map->mask;
    AnyMapEntry *entry = &map->entries[pos];
    
    if (!entry->occupied) return false;
    if (entry->hash == hash && astra_any_equal(entry->key, key)) {
      *out_value = entry->value;
      return true;
    }
  }
  
  return false;
}

static bool astra_any_map_has(AstraAnyMap *map, uintptr_t key) {
  uintptr_t dummy;
  return astra_any_map_get(map, key, &dummy);
}

static void astra_any_map_free(AstraAnyMap *map) {
  if (map) {
    free(map->entries);
    free(map);
  }
}
#endif

uintptr_t astra_len_any(uintptr_t v) {
  AstraAnySlot *entry = astra_any_find_slot(v);
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
#endif

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

uintptr_t __stdin_read_line_impl(void) {
  size_t cap = 128;
  char *buf = (char *)malloc(cap);
  if (buf == NULL) {
    return (uintptr_t)astra_strdup_s("");
  }
  if (fgets(buf, (int)cap, stdin) == NULL) {
    free(buf);
    return (uintptr_t)astra_strdup_s("");
  }
  size_t len = strlen(buf);
  while (len > 0 && buf[len - 1] != '\n' && !feof(stdin)) {
    size_t next_cap = cap * 2;
    char *grown = (char *)realloc(buf, next_cap);
    if (grown == NULL) {
      break;
    }
    buf = grown;
    cap = next_cap;
    if (fgets(buf + len, (int)(cap - len), stdin) == NULL) {
      break;
    }
    len = strlen(buf);
  }
  len = strlen(buf);
  if (len > 0 && buf[len - 1] == '\n') {
    buf[len - 1] = '\0';
  }
  char *out = astra_strdup_s(buf);
  free(buf);
  return (uintptr_t)out;
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

#if defined(ASTRA_ENABLE_ANY_RUNTIME)
uintptr_t astra_args(void) {
  astra_load_cli_args();
  uintptr_t h = astra_list_new();
  for (size_t i = 0; i < g_cli_argc; i++) {
    astra_list_push(h, astra_any_box_str((uintptr_t)g_cli_argv[i]));
  }
  return h;
}
#endif

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
  uint32_t generation;  // Generation counter for handle validation
  bool live;            // Whether this slot is in use
#if defined(_WIN32)
  HANDLE thread;
#else
  pthread_t thread;
#endif
} SpawnSlot;

typedef struct {
  SpawnSlot *slots;
  size_t capacity;
  size_t next_free;     // Index of next free slot to try
  uint32_t next_generation;
  bool initialized;     // Lazy initialization flag
} SpawnSlotTable;

static SpawnSlotTable g_spawn_table = {NULL, 0, 0, 1, false};

typedef struct {
  bool used;
  uint32_t generation;  // Generation counter for handle validation
  bool live;            // Whether this slot is in use
#if defined(_WIN32)
  SRWLOCK lock;
#else
  pthread_mutex_t lock;
#endif
} MutexSlot;

typedef struct {
  MutexSlot *slots;
  size_t capacity;
  size_t next_free;     // Index of next free slot to try
  uint32_t next_generation;
  bool initialized;     // Lazy initialization flag
} MutexSlotTable;

static MutexSlotTable g_mutex_table = {NULL, 0, 0, 1, false};

typedef struct {
  bool used;
  bool closed;
  size_t head;
  size_t len;
  size_t cap;
  uintptr_t *items;
  uint32_t generation;  // Generation counter for handle validation
  bool live;            // Whether this slot is in use
#if defined(_WIN32)
  SRWLOCK lock;
  CONDITION_VARIABLE cv;
#else
  pthread_mutex_t lock;
  pthread_cond_t cv;
#endif
} ChanSlot;

typedef struct {
  ChanSlot *slots;
  size_t capacity;
  size_t next_free;     // Index of next free slot to try
  uint32_t next_generation;
  bool initialized;     // Lazy initialization flag
} ChanSlotTable;

static ChanSlotTable g_chan_table = {NULL, 0, 0, 1, false};

// ============================================================================
// LAZY THREADING SLOT TABLE OPERATIONS
// ============================================================================

// Generic slot table operations (shared between spawn, mutex, chan)
static bool astra_slot_table_reserve(void **table_ptr, size_t *capacity_ptr, size_t element_size, size_t min_capacity) {
  size_t current_cap = *capacity_ptr;
  if (current_cap >= min_capacity) {
    return true;
  }
  size_t next = current_cap == 0 ? 8 : current_cap * 2;
  while (next < min_capacity) {
    next *= 2;
  }
  
  void *new_table = realloc(*table_ptr, next * element_size);
  if (new_table == NULL) {
    return false;
  }
  
  // Initialize new slots
  char *bytes = (char *)new_table;
  for (size_t i = current_cap; i < next; i++) {
    // Set live to false and generation to 0 for all new slots
    bool *live_ptr = (bool *)(bytes + i * element_size + offsetof(SpawnSlot, live));
    uint32_t *gen_ptr = (uint32_t *)(bytes + i * element_size + offsetof(SpawnSlot, generation));
    *live_ptr = false;
    *gen_ptr = 0;
  }
  
  *table_ptr = new_table;
  *capacity_ptr = next;
  return true;
}

// Spawn slot table operations
static bool astra_spawn_table_init(void) {
  if (g_spawn_table.initialized) {
    return true;
  }
  
  // Initialize with a small initial capacity
  g_spawn_table.slots = (SpawnSlot *)calloc(8, sizeof(SpawnSlot));
  if (g_spawn_table.slots == NULL) {
    return false;
  }
  
  g_spawn_table.capacity = 8;
  g_spawn_table.next_free = 0;
  g_spawn_table.next_generation = 1;
  g_spawn_table.initialized = true;
  return true;
}

static uintptr_t astra_spawn_alloc_slot(void) {
  if (!g_spawn_table.initialized && !astra_spawn_table_init()) {
    return 0;
  }
  
  if (!astra_slot_table_reserve((void **)&g_spawn_table.slots, &g_spawn_table.capacity, 
                               sizeof(SpawnSlot), g_spawn_table.next_free + 1)) {
    return 0;
  }
  
  // Find the next available slot
  size_t start = g_spawn_table.next_free;
  for (size_t i = start; i < g_spawn_table.capacity; i++) {
    if (!g_spawn_table.slots[i].live) {
      g_spawn_table.slots[i].live = true;
      g_spawn_table.slots[i].generation = g_spawn_table.next_generation++;
      g_spawn_table.slots[i].value = 0;
      g_spawn_table.slots[i].joined = false;
      g_spawn_table.slots[i].has_thread = false;
      g_spawn_table.next_free = i + 1;
      
      // Pack slot index and generation into handle
      uintptr_t handle = ((uintptr_t)g_spawn_table.slots[i].generation << 32) | (uintptr_t)i;
      return handle;
    }
  }
  
  // If we didn't find one, wrap around and check from beginning
  for (size_t i = 0; i < start; i++) {
    if (!g_spawn_table.slots[i].live) {
      g_spawn_table.slots[i].live = true;
      g_spawn_table.slots[i].generation = g_spawn_table.next_generation++;
      g_spawn_table.slots[i].value = 0;
      g_spawn_table.slots[i].joined = false;
      g_spawn_table.slots[i].has_thread = false;
      g_spawn_table.next_free = i + 1;
      
      uintptr_t handle = ((uintptr_t)g_spawn_table.slots[i].generation << 32) | (uintptr_t)i;
      return handle;
    }
  }
  
  // No free slots available
  return 0;
}

static SpawnSlot *astra_spawn_find_slot(uintptr_t handle) {
  if (!g_spawn_table.initialized) {
    return NULL;
  }
  
  size_t slot_index = (size_t)(handle & 0xFFFFFFFF);
  uint32_t generation = (uint32_t)(handle >> 32);
  
  if (slot_index >= g_spawn_table.capacity) {
    return NULL;
  }
  
  SpawnSlot *slot = &g_spawn_table.slots[slot_index];
  if (!slot->live || slot->generation != generation) {
    return NULL;
  }
  
  return slot;
}

static void astra_spawn_free_slot(uintptr_t handle) {
  if (!g_spawn_table.initialized) {
    return;
  }
  
  size_t slot_index = (size_t)(handle & 0xFFFFFFFF);
  uint32_t generation = (uint32_t)(handle >> 32);
  
  if (slot_index >= g_spawn_table.capacity) {
    return;
  }
  
  SpawnSlot *slot = &g_spawn_table.slots[slot_index];
  if (slot->live && slot->generation == generation) {
    slot->live = false;
    slot->generation = 0;
    if (slot_index < g_spawn_table.next_free) {
      g_spawn_table.next_free = slot_index;
    }
  }
}

// Mutex slot table operations
static bool astra_mutex_table_init(void) {
  if (g_mutex_table.initialized) {
    return true;
  }
  
  g_mutex_table.slots = (MutexSlot *)calloc(8, sizeof(MutexSlot));
  if (g_mutex_table.slots == NULL) {
    return false;
  }
  
  g_mutex_table.capacity = 8;
  g_mutex_table.next_free = 0;
  g_mutex_table.next_generation = 1;
  g_mutex_table.initialized = true;
  return true;
}

static uintptr_t astra_mutex_alloc_slot(void) {
  if (!g_mutex_table.initialized && !astra_mutex_table_init()) {
    return 0;
  }
  
  if (!astra_slot_table_reserve((void **)&g_mutex_table.slots, &g_mutex_table.capacity, 
                               sizeof(MutexSlot), g_mutex_table.next_free + 1)) {
    return 0;
  }
  
  size_t start = g_mutex_table.next_free;
  for (size_t i = start; i < g_mutex_table.capacity; i++) {
    if (!g_mutex_table.slots[i].live) {
      g_mutex_table.slots[i].live = true;
      g_mutex_table.slots[i].generation = g_mutex_table.next_generation++;
      g_mutex_table.slots[i].used = false;
#if defined(_WIN32)
      InitializeSRWLock(&g_mutex_table.slots[i].lock);
#else
      pthread_mutex_init(&g_mutex_table.slots[i].lock, NULL);
#endif
      g_mutex_table.next_free = i + 1;
      
      uintptr_t handle = ((uintptr_t)g_mutex_table.slots[i].generation << 32) | (uintptr_t)i;
      return handle;
    }
  }
  
  for (size_t i = 0; i < start; i++) {
    if (!g_mutex_table.slots[i].live) {
      g_mutex_table.slots[i].live = true;
      g_mutex_table.slots[i].generation = g_mutex_table.next_generation++;
      g_mutex_table.slots[i].used = false;
#if defined(_WIN32)
      InitializeSRWLock(&g_mutex_table.slots[i].lock);
#else
      pthread_mutex_init(&g_mutex_table.slots[i].lock, NULL);
#endif
      g_mutex_table.next_free = i + 1;
      
      uintptr_t handle = ((uintptr_t)g_mutex_table.slots[i].generation << 32) | (uintptr_t)i;
      return handle;
    }
  }
  
  return 0;
}

static MutexSlot *astra_mutex_find_slot(uintptr_t handle) {
  if (!g_mutex_table.initialized) {
    return NULL;
  }
  
  size_t slot_index = (size_t)(handle & 0xFFFFFFFF);
  uint32_t generation = (uint32_t)(handle >> 32);
  
  if (slot_index >= g_mutex_table.capacity) {
    return NULL;
  }
  
  MutexSlot *slot = &g_mutex_table.slots[slot_index];
  if (!slot->live || slot->generation != generation) {
    return NULL;
  }
  
  return slot;
}

// Channel slot table operations
static bool astra_chan_table_init(void) {
  if (g_chan_table.initialized) {
    return true;
  }
  
  g_chan_table.slots = (ChanSlot *)calloc(8, sizeof(ChanSlot));
  if (g_chan_table.slots == NULL) {
    return false;
  }
  
  g_chan_table.capacity = 8;
  g_chan_table.next_free = 0;
  g_chan_table.next_generation = 1;
  g_chan_table.initialized = true;
  return true;
}

static uintptr_t astra_chan_alloc_slot(void) {
  if (!g_chan_table.initialized && !astra_chan_table_init()) {
    return 0;
  }
  
  if (!astra_slot_table_reserve((void **)&g_chan_table.slots, &g_chan_table.capacity, 
                               sizeof(ChanSlot), g_chan_table.next_free + 1)) {
    return 0;
  }
  
  size_t start = g_chan_table.next_free;
  for (size_t i = start; i < g_chan_table.capacity; i++) {
    if (!g_chan_table.slots[i].live) {
      g_chan_table.slots[i].live = true;
      g_chan_table.slots[i].generation = g_chan_table.next_generation++;
      g_chan_table.slots[i].used = false;
      g_chan_table.slots[i].closed = false;
      g_chan_table.slots[i].head = 0;
      g_chan_table.slots[i].len = 0;
      g_chan_table.slots[i].cap = 0;
      g_chan_table.slots[i].items = NULL;
#if defined(_WIN32)
      InitializeSRWLock(&g_chan_table.slots[i].lock);
      InitializeConditionVariable(&g_chan_table.slots[i].cv);
#else
      pthread_mutex_init(&g_chan_table.slots[i].lock, NULL);
      pthread_cond_init(&g_chan_table.slots[i].cv, NULL);
#endif
      g_chan_table.next_free = i + 1;
      
      uintptr_t handle = ((uintptr_t)g_chan_table.slots[i].generation << 32) | (uintptr_t)i;
      return handle;
    }
  }
  
  for (size_t i = 0; i < start; i++) {
    if (!g_chan_table.slots[i].live) {
      g_chan_table.slots[i].live = true;
      g_chan_table.slots[i].generation = g_chan_table.next_generation++;
      g_chan_table.slots[i].used = false;
      g_chan_table.slots[i].closed = false;
      g_chan_table.slots[i].head = 0;
      g_chan_table.slots[i].len = 0;
      g_chan_table.slots[i].cap = 0;
      g_chan_table.slots[i].items = NULL;
#if defined(_WIN32)
      InitializeSRWLock(&g_chan_table.slots[i].lock);
      InitializeConditionVariable(&g_chan_table.slots[i].cv);
#else
      pthread_mutex_init(&g_chan_table.slots[i].lock, NULL);
      pthread_cond_init(&g_chan_table.slots[i].cv, NULL);
#endif
      g_chan_table.next_free = i + 1;
      
      uintptr_t handle = ((uintptr_t)g_chan_table.slots[i].generation << 32) | (uintptr_t)i;
      return handle;
    }
  }
  
  return 0;
}

static ChanSlot *astra_chan_find_slot(uintptr_t handle) {
  if (!g_chan_table.initialized) {
    return NULL;
  }
  
  size_t slot_index = (size_t)(handle & 0xFFFFFFFF);
  uint32_t generation = (uint32_t)(handle >> 32);
  
  if (slot_index >= g_chan_table.capacity) {
    return NULL;
  }
  
  ChanSlot *slot = &g_chan_table.slots[slot_index];
  if (!slot->live || slot->generation != generation) {
    return NULL;
  }
  
  return slot;
}

static bool astra_chan_reserve(ChanSlot *slot, size_t want) {
  if (slot->cap >= want) {
    return true;
  }
  size_t next = slot->cap == 0 ? 8 : slot->cap * 2;
  while (next < want) {
    next *= 2;
  }
  uintptr_t *p = (uintptr_t *)realloc(slot->items, next * sizeof(uintptr_t));
  if (p == NULL) {
    return false;
  }
  slot->items = p;
  slot->cap = next;
  return true;
}

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

  // Allocate a slot from the table (lazy initialization handled internally)
  uintptr_t handle = astra_spawn_alloc_slot();
  if (handle == 0) {
    free(ctx);
    return 0;
  }

  SpawnSlot *slot = astra_spawn_find_slot(handle);
  if (slot == NULL) {
    free(ctx);
    return 0;
  }

  slot->has_thread = true;

#if defined(_WIN32)
  HANDLE thread = CreateThread(NULL, 0, astra_spawn_trampoline, (LPVOID)ctx, 0, NULL);
  if (thread == NULL) {
    slot->has_thread = false;
    slot->live = false;  // Free the slot
    free(ctx);
    return 0;
  }
  slot->thread = thread;
#else
  pthread_t th;
  if (pthread_create(&th, NULL, astra_spawn_trampoline, (void *)ctx) != 0) {
    slot->has_thread = false;
    slot->live = false;  // Free the slot
    free(ctx);
    return 0;
  }
  slot->thread = th;
#endif

  return handle;
}

uintptr_t astra_spawn_store(uintptr_t value) {
  uintptr_t handle = astra_spawn_alloc_slot();
  if (handle == 0) {
    return 0;
  }

  SpawnSlot *slot = astra_spawn_find_slot(handle);
  if (slot == NULL) {
    return 0;
  }

  slot->value = value;
  slot->joined = true;
  slot->has_thread = false;
  return handle;
}

uintptr_t astra_join(uintptr_t handle) {
  SpawnSlot *slot = astra_spawn_find_slot(handle);
  if (slot == NULL) {
#if defined(ASTRA_ENABLE_ANY_RUNTIME)
    return astra_any_box_i64(0);
#else
    return 0;
#endif
  }
  
  if (slot->joined) {
    uintptr_t done_value = slot->value;
    slot->live = false;  // Free the slot
#if defined(ASTRA_ENABLE_ANY_RUNTIME)
    return astra_any_box_i64((int64_t)done_value);
#else
    return done_value;
#endif
  }
  
  bool has_thread = slot->has_thread;
  // Mark as joining immediately to prevent reuse
  slot->joined = true;
  
#if defined(_WIN32)
  HANDLE th = slot->thread;
#else
  pthread_t th = slot->thread;
#endif

  uintptr_t worker_raw = 0;
  
#if defined(_WIN32)
  if (th != NULL) {
    DWORD code;
    if (GetExitCodeThread(th, &code) && code == STILL_ACTIVE) {
      WaitForSingleObject(th, INFINITE);
    }
    if (GetExitCodeThread(th, &code)) {
      worker_raw = (uintptr_t)code;
    }
    CloseHandle(th);
  }
#else
  if (th != 0) {
    void *ret_ptr = NULL;
    if (pthread_join(th, &ret_ptr) == 0) {
      worker_raw = (uintptr_t)ret_ptr;
    }
  }
#endif

  slot->has_thread = false;
  slot->value = worker_raw;
  
#if defined(ASTRA_ENABLE_ANY_RUNTIME)
  uintptr_t boxed = astra_any_box_i64((int64_t)worker_raw);
#else
  uintptr_t boxed = worker_raw;
#endif
  
  // Double-check that the entry is still valid
  SpawnSlot *check_slot = astra_spawn_find_slot(handle);
  if (check_slot == slot && check_slot->has_thread == false) {
    slot->value = boxed;
    slot->has_thread = false;
  }
  
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

uintptr_t astra_mutex_new(void) {
  uintptr_t handle = astra_mutex_alloc_slot();
  if (handle == 0) {
    return 0;
  }

  MutexSlot *slot = astra_mutex_find_slot(handle);
  if (slot == NULL) {
    return 0;
  }

  slot->used = true;
  return handle;
}

uintptr_t astra_mutex_lock(uintptr_t handle, uintptr_t owner_tid) {
  (void)owner_tid;
  MutexSlot *slot = astra_mutex_find_slot(handle);
  if (slot == NULL) {
    return (uintptr_t)-1;
  }

#if defined(_WIN32)
  AcquireSRWLockExclusive(&slot->lock);
  return 0;
#else
  return pthread_mutex_lock(&slot->lock) == 0 ? 0 : (uintptr_t)-1;
#endif
}

uintptr_t astra_mutex_unlock(uintptr_t mid, uintptr_t owner_tid) {
  (void)owner_tid;
  MutexSlot *slot = astra_mutex_find_slot(mid);
  if (slot == NULL) {
    return (uintptr_t)-1;
  }

#if defined(_WIN32)
  ReleaseSRWLockExclusive(&slot->lock);
  return 0;
#else
  return pthread_mutex_unlock(&slot->lock) == 0 ? 0 : (uintptr_t)-1;
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

uintptr_t astra_chan_new(void) {
  uintptr_t handle = astra_chan_alloc_slot();
  if (handle == 0) {
    return 0;
  }

  ChanSlot *slot = astra_chan_find_slot(handle);
  if (slot == NULL) {
    return 0;
  }

  slot->used = true;
  slot->closed = false;
  slot->head = 0;
  slot->len = 0;
  return handle;
}

uintptr_t astra_chan_send(uintptr_t handle, uintptr_t value) {
  ChanSlot *slot = astra_chan_find_slot(handle);
  if (slot == NULL) {
    return (uintptr_t)-1;
  }

#if defined(_WIN32)
  AcquireSRWLockExclusive(&slot->lock);
#else
  pthread_mutex_lock(&slot->lock);
#endif

  if (slot->closed) {
#if defined(_WIN32)
    ReleaseSRWLockExclusive(&slot->lock);
#else
    pthread_mutex_unlock(&slot->lock);
#endif
    return (uintptr_t)-1;
  }

  if (!astra_chan_reserve(slot, slot->len + 1)) {
#if defined(_WIN32)
    ReleaseSRWLockExclusive(&slot->lock);
#else
    pthread_mutex_unlock(&slot->lock);
#endif
    return (uintptr_t)-1;
  }

  slot->items[slot->len] = value;
  slot->len += 1;

#if defined(_WIN32)
  WakeConditionVariable(&slot->cv);
  ReleaseSRWLockExclusive(&slot->lock);
#else
  pthread_cond_signal(&slot->cv);
  pthread_mutex_unlock(&slot->lock);
#endif

  return 0;
}

uintptr_t astra_chan_recv_try(uintptr_t handle) {
  ChanSlot *slot = astra_chan_find_slot(handle);
  if (slot == NULL) {
#if defined(ASTRA_ENABLE_ANY_RUNTIME)
    return astra_any_box_none();
#else
    return 0;
#endif
  }

#if defined(_WIN32)
  AcquireSRWLockExclusive(&slot->lock);
#else
  pthread_mutex_lock(&slot->lock);
#endif

  uintptr_t out;
  if (slot->head >= slot->len) {
#if defined(ASTRA_ENABLE_ANY_RUNTIME)
    out = astra_any_box_none();
#else
    out = 0;
#endif
  } else {
    out = slot->items[slot->head++];
    if (slot->head >= slot->len) {
      slot->head = 0;
      slot->len = 0;
    }
  }

#if defined(_WIN32)
  ReleaseSRWLockExclusive(&slot->lock);
#else
  pthread_mutex_unlock(&slot->lock);
#endif

  return out;
}

uintptr_t astra_chan_recv_blocking(uintptr_t handle) {
  ChanSlot *slot = astra_chan_find_slot(handle);
  if (slot == NULL) {
#if defined(ASTRA_ENABLE_ANY_RUNTIME)
    return astra_any_box_none();
#else
    return 0;
#endif
  }

#if defined(_WIN32)
  AcquireSRWLockExclusive(&slot->lock);
#else
  pthread_mutex_lock(&slot->lock);
#endif

  while (slot->head >= slot->len && !slot->closed) {
#if defined(_WIN32)
    SleepConditionVariableSRW(&slot->cv, &slot->lock, INFINITE, 0);
#else
    pthread_cond_wait(&slot->cv, &slot->lock);
#endif
  }

  uintptr_t out;
  if (slot->head >= slot->len && slot->closed) {
#if defined(ASTRA_ENABLE_ANY_RUNTIME)
    out = astra_any_box_none();
#else
    out = 0;
#endif
  } else {
    out = slot->items[slot->head++];
    if (slot->head >= slot->len) {
      slot->head = 0;
      slot->len = 0;
    }
  }

#if defined(_WIN32)
  ReleaseSRWLockExclusive(&slot->lock);
#else
  pthread_mutex_unlock(&slot->lock);
#endif

  return out;
}

uintptr_t astra_chan_close(uintptr_t handle) {
  ChanSlot *slot = astra_chan_find_slot(handle);
  if (slot == NULL) {
    return 1;
  }

#if defined(_WIN32)
  AcquireSRWLockExclusive(&slot->lock);
  slot->closed = true;
  WakeAllConditionVariable(&slot->cv);
  ReleaseSRWLockExclusive(&slot->lock);
  return 0;
#else
  if (pthread_mutex_lock(&slot->lock) != 0) {
    return 1;
  }
  slot->closed = true;
  (void)pthread_cond_broadcast(&slot->cv);
  (void)pthread_mutex_unlock(&slot->lock);
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

// ============================================================================
// STRING BUILDER (Public API)
// ============================================================================

typedef struct {
  char *data;
  size_t len;
  size_t cap;
} StringBuilder;

// Create a new StringBuilder
uintptr_t astra_string_builder_new(void) {
  StringBuilder *sb = (StringBuilder *)malloc(sizeof(StringBuilder));
  if (sb == NULL) {
    return 0;
  }
  sb->data = NULL;
  sb->len = 0;
  sb->cap = 0;
  return (uintptr_t)sb;
}

// Free a StringBuilder (does not return the string)
void astra_string_builder_free(uintptr_t sb_handle) {
  StringBuilder *sb = (StringBuilder *)sb_handle;
  if (sb) {
    if (sb->data) {
      free(sb->data);
    }
    free(sb);
  }
}

// Reserve capacity in StringBuilder
bool astra_string_builder_reserve(uintptr_t sb_handle, size_t capacity) {
  StringBuilder *sb = (StringBuilder *)sb_handle;
  if (sb == NULL) {
    return false;
  }
  
  if (sb->cap >= capacity) {
    return true;
  }
  
  size_t next = sb->cap == 0 ? 64 : sb->cap * 2;
  while (next < capacity) {
    next *= 2;
  }
  
  char *p = (char *)realloc(sb->data, next);
  if (p == NULL) {
    return false;
  }
  
  sb->data = p;
  sb->cap = next;
  return true;
}

// Append a string to StringBuilder
bool astra_string_builder_append_str(uintptr_t sb_handle, uintptr_t str_ptr) {
  StringBuilder *sb = (StringBuilder *)sb_handle;
  const char *str = (const char *)str_ptr;
  if (sb == NULL || str == NULL) {
    return false;
  }
  
  size_t str_len = strlen(str);
  if (!astra_string_builder_reserve(sb_handle, sb->len + str_len + 1)) {
    return false;
  }
  
  memcpy(sb->data + sb->len, str, str_len);
  sb->len += str_len;
  if (sb->data) {
    sb->data[sb->len] = '\0';
  }
  return true;
}

// Append a character to StringBuilder
bool astra_string_builder_append_char(uintptr_t sb_handle, char ch) {
  StringBuilder *sb = (StringBuilder *)sb_handle;
  if (sb == NULL) {
    return false;
  }
  
  if (!astra_string_builder_reserve(sb_handle, sb->len + 2)) {
    return false;
  }
  
  sb->data[sb->len++] = ch;
  sb->data[sb->len] = '\0';
  return true;
}

// Append an integer to StringBuilder
bool astra_string_builder_append_int(uintptr_t sb_handle, int64_t value) {
  StringBuilder *sb = (StringBuilder *)sb_handle;
  if (sb == NULL) {
    return false;
  }
  
  // Buffer sufficient for 64-bit integer
  char buffer[32];
  snprintf(buffer, sizeof(buffer), "%lld", (long long)value);
  return astra_string_builder_append_str(sb_handle, (uintptr_t)buffer);
}

// Append a float to StringBuilder
bool astra_string_builder_append_float(uintptr_t sb_handle, double value) {
  StringBuilder *sb = (StringBuilder *)sb_handle;
  if (sb == NULL) {
    return false;
  }
  
  // Buffer sufficient for double
  char buffer[64];
  snprintf(buffer, sizeof(buffer), "%.6g", value);
  return astra_string_builder_append_str(sb_handle, (uintptr_t)buffer);
}

// Get current length of StringBuilder
size_t astra_string_builder_len(uintptr_t sb_handle) {
  StringBuilder *sb = (StringBuilder *)sb_handle;
  if (sb == NULL) {
    return 0;
  }
  return sb->len;
}

// Clear StringBuilder (keep capacity)
void astra_string_builder_clear(uintptr_t sb_handle) {
  StringBuilder *sb = (StringBuilder *)sb_handle;
  if (sb && sb->data) {
    sb->len = 0;
    sb->data[0] = '\0';
  }
}

// Finish StringBuilder and return heap-allocated string
uintptr_t astra_string_builder_finish(uintptr_t sb_handle) {
  StringBuilder *sb = (StringBuilder *)sb_handle;
  if (sb == NULL) {
    return (uintptr_t)astra_strdup_s("");
  }
  
  if (sb->data == NULL) {
    free(sb);
    return (uintptr_t)astra_strdup_s("");
  }
  
  char *out = (char *)astra_heap_alloc(sb->len + 1);
  if (out == NULL) {
    free(sb->data);
    free(sb);
    return (uintptr_t)astra_strdup_s("");
  }
  
  memcpy(out, sb->data, sb->len + 1);
  free(sb->data);
  free(sb);
  return (uintptr_t)out;
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

#if defined(ASTRA_ENABLE_ANY_RUNTIME)
static bool astra_json_write_map_key(AstraBuf *buf, uintptr_t key_any);

static bool astra_json_write_any(AstraBuf *buf, uintptr_t v, int depth) {
  if (depth > 256) {
    return astra_buf_append(buf, "null");
  }
  AstraAnySlot *entry = astra_any_find_slot(v);
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
  AstraAnySlot *entry = astra_any_find_slot(key_any);
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
#endif

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

#if defined(ASTRA_ENABLE_ANY_RUNTIME)
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
#endif

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

#if defined(ASTRA_ENABLE_ANY_RUNTIME)
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
#endif

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

// Backward compatibility print functions for stdlib
void astra_print_int(int64_t x) {
  printf("%lld", (long long)x);
}

void astra_print_bool(int8_t x) {
  printf("%s", x ? "true" : "false");
}

void astra_print_float(double x) {
  printf("%.6g", x);
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

// String conversion functions
uintptr_t astra_int_to_str(int64_t value) {
  // Buffer large enough for 64-bit integer + sign + null terminator
  char buffer[32];
  int len = snprintf(buffer, sizeof(buffer), "%lld", (long long)value);
  if (len < 0 || len >= (int)sizeof(buffer)) {
    return (uintptr_t)astra_strdup_s("");
  }
  char *result = (char *)astra_heap_alloc(len + 1);
  if (result == NULL) {
    return (uintptr_t)astra_strdup_s("");
  }
  memcpy(result, buffer, len + 1);
  return (uintptr_t)result;
}

uintptr_t astra_uint_to_str(uint64_t value) {
  char buffer[32];
  int len = snprintf(buffer, sizeof(buffer), "%llu", (unsigned long long)value);
  if (len < 0 || len >= (int)sizeof(buffer)) {
    return (uintptr_t)astra_strdup_s("");
  }
  char *result = (char *)astra_heap_alloc(len + 1);
  if (result == NULL) {
    return (uintptr_t)astra_strdup_s("");
  }
  memcpy(result, buffer, len + 1);
  return (uintptr_t)result;
}

uintptr_t astra_float_to_str(double value) {
  char buffer[64];
  int len = snprintf(buffer, sizeof(buffer), "%.15g", value);
  if (len < 0 || len >= (int)sizeof(buffer)) {
    return (uintptr_t)astra_strdup_s("");
  }
  char *result = (char *)astra_heap_alloc(len + 1);
  if (result == NULL) {
    return (uintptr_t)astra_strdup_s("");
  }
  memcpy(result, buffer, len + 1);
  return (uintptr_t)result;
}

uintptr_t astra_bool_to_str(int8_t value) {
  const char *str = value ? "true" : "false";
  char *result = (char *)astra_heap_alloc(strlen(str) + 1);
  if (result == NULL) {
    return (uintptr_t)astra_strdup_s("");
  }
  strcpy(result, str);
  return (uintptr_t)result;
}

typedef struct {
  uint64_t len;
  uint8_t *data;
} AstraRuntimeVecHeader;

static uintptr_t astra_make_vec_u8(const uint8_t *src, size_t len) {
  AstraRuntimeVecHeader *hdr = (AstraRuntimeVecHeader *)astra_heap_alloc(sizeof(AstraRuntimeVecHeader));
  if (hdr == NULL) {
    return 0;
  }
  hdr->len = (uint64_t)len;
  if (len == 0) {
    hdr->data = NULL;
    return (uintptr_t)hdr;
  }
  uint8_t *out = (uint8_t *)astra_heap_alloc(len);
  if (out == NULL) {
    hdr->len = 0;
    hdr->data = NULL;
    return (uintptr_t)hdr;
  }
  memcpy(out, src, len);
  hdr->data = out;
  return (uintptr_t)hdr;
}

static bool astra_read_vec_u8(uintptr_t vec_ptr, const uint8_t **data_out, size_t *len_out) {
  if (data_out == NULL || len_out == NULL) {
    return false;
  }
  if (vec_ptr == 0) {
    *data_out = NULL;
    *len_out = 0;
    return false;
  }
  AstraRuntimeVecHeader *hdr = (AstraRuntimeVecHeader *)vec_ptr;
  *len_out = (size_t)hdr->len;
  *data_out = (const uint8_t *)hdr->data;
  return true;
}

static uintptr_t astra_make_vec_str(char **items, size_t len) {
  AstraRuntimeVecHeader *hdr = (AstraRuntimeVecHeader *)astra_heap_alloc(sizeof(AstraRuntimeVecHeader));
  if (hdr == NULL) {
    return 0;
  }
  hdr->len = (uint64_t)len;
  if (len == 0) {
    hdr->data = NULL;
    return (uintptr_t)hdr;
  }
  char **arr = (char **)astra_heap_alloc(len * sizeof(char *));
  if (arr == NULL) {
    hdr->len = 0;
    hdr->data = NULL;
    return (uintptr_t)hdr;
  }
  memcpy(arr, items, len * sizeof(char *));
  hdr->data = (uint8_t *)arr;
  return (uintptr_t)hdr;
}

static char *astra_substr_copy(const char *s, size_t start, size_t len) {
  char *out = (char *)astra_heap_alloc(len + 1);
  if (out == NULL) {
    return astra_strdup_s("");
  }
  memcpy(out, s + start, len);
  out[len] = '\0';
  return out;
}

static bool astra_is_space_ch(unsigned char ch) {
  return ch == ' ' || ch == '\t' || ch == '\n' || ch == '\r' || ch == '\f' || ch == '\v';
}

static int astra_hex_nibble(char ch) {
  if (ch >= '0' && ch <= '9') return ch - '0';
  if (ch >= 'a' && ch <= 'f') return 10 + (ch - 'a');
  if (ch >= 'A' && ch <= 'F') return 10 + (ch - 'A');
  return -1;
}

static bool astra_url_unreserved(unsigned char ch) {
  if ((ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9')) return true;
  return ch == '-' || ch == '_' || ch == '.' || ch == '~';
}

int64_t __str_char_at_impl(uintptr_t s_ptr, int64_t index) {
  const char *s = (const char *)s_ptr;
  if (s == NULL || index < 0) return 0;
  size_t n = strlen(s);
  size_t i = (size_t)index;
  if (i >= n) return 0;
  return (int64_t)(unsigned char)s[i];
}

uintptr_t __str_from_char_impl(int64_t c) {
  char *out = (char *)astra_heap_alloc(2);
  if (out == NULL) return (uintptr_t)astra_strdup_s("");
  out[0] = (char)(c & 0xFF);
  out[1] = '\0';
  return (uintptr_t)out;
}

uintptr_t __str_substring_impl(uintptr_t s_ptr, int64_t start, int64_t length) {
  const char *s = (const char *)s_ptr;
  if (s == NULL) return (uintptr_t)astra_strdup_s("");
  if (start < 0 || length < 0) return (uintptr_t)astra_strdup_s("");
  size_t n = strlen(s);
  size_t st = (size_t)start;
  size_t ln = (size_t)length;
  if (st >= n) return (uintptr_t)astra_strdup_s("");
  if (st + ln > n) ln = n - st;
  return (uintptr_t)astra_substr_copy(s, st, ln);
}

uintptr_t __str_to_upper_impl(uintptr_t s_ptr) {
  const char *s = (const char *)s_ptr;
  if (s == NULL) return (uintptr_t)astra_strdup_s("");
  size_t n = strlen(s);
  char *out = (char *)astra_heap_alloc(n + 1);
  if (out == NULL) return (uintptr_t)astra_strdup_s("");
  for (size_t i = 0; i < n; i++) {
    char ch = s[i];
    out[i] = (ch >= 'a' && ch <= 'z') ? (char)(ch - 32) : ch;
  }
  out[n] = '\0';
  return (uintptr_t)out;
}

uintptr_t __str_to_lower_impl(uintptr_t s_ptr) {
  const char *s = (const char *)s_ptr;
  if (s == NULL) return (uintptr_t)astra_strdup_s("");
  size_t n = strlen(s);
  char *out = (char *)astra_heap_alloc(n + 1);
  if (out == NULL) return (uintptr_t)astra_strdup_s("");
  for (size_t i = 0; i < n; i++) {
    char ch = s[i];
    out[i] = (ch >= 'A' && ch <= 'Z') ? (char)(ch + 32) : ch;
  }
  out[n] = '\0';
  return (uintptr_t)out;
}

uintptr_t __str_trim_start_impl(uintptr_t s_ptr) {
  const char *s = (const char *)s_ptr;
  if (s == NULL) return (uintptr_t)astra_strdup_s("");
  size_t n = strlen(s);
  size_t st = 0;
  while (st < n && astra_is_space_ch((unsigned char)s[st])) st++;
  return (uintptr_t)astra_substr_copy(s, st, n - st);
}

uintptr_t __str_trim_end_impl(uintptr_t s_ptr) {
  const char *s = (const char *)s_ptr;
  if (s == NULL) return (uintptr_t)astra_strdup_s("");
  size_t n = strlen(s);
  size_t end = n;
  while (end > 0 && astra_is_space_ch((unsigned char)s[end - 1])) end--;
  return (uintptr_t)astra_substr_copy(s, 0, end);
}

uintptr_t __str_trim_impl(uintptr_t s_ptr) {
  uintptr_t left = __str_trim_start_impl(s_ptr);
  return __str_trim_end_impl(left);
}

int64_t __str_find_impl(uintptr_t s_ptr, uintptr_t pattern_ptr) {
  const char *s = (const char *)s_ptr;
  const char *pattern = (const char *)pattern_ptr;
  if (s == NULL || pattern == NULL) return -1;
  if (pattern[0] == '\0') return 0;
  const char *hit = strstr(s, pattern);
  if (hit == NULL) return -1;
  return (int64_t)(hit - s);
}

uintptr_t __str_replace_impl(uintptr_t s_ptr, uintptr_t pattern_ptr, uintptr_t replacement_ptr) {
  const char *s = (const char *)s_ptr;
  const char *pattern = (const char *)pattern_ptr;
  const char *replacement = (const char *)replacement_ptr;
  if (s == NULL) return (uintptr_t)astra_strdup_s("");
  if (pattern == NULL || pattern[0] == '\0') return (uintptr_t)astra_strdup_s(s);
  if (replacement == NULL) replacement = "";

  size_t s_len = strlen(s);
  size_t p_len = strlen(pattern);
  size_t r_len = strlen(replacement);

  size_t count = 0;
  const char *cur = s;
  while (true) {
    const char *hit = strstr(cur, pattern);
    if (hit == NULL) break;
    count++;
    cur = hit + p_len;
  }

  if (count == 0) return (uintptr_t)astra_strdup_s(s);

  size_t out_len = s_len + count * (r_len - p_len);
  char *out = (char *)astra_heap_alloc(out_len + 1);
  if (out == NULL) return (uintptr_t)astra_strdup_s("");

  size_t wi = 0;
  cur = s;
  while (true) {
    const char *hit = strstr(cur, pattern);
    if (hit == NULL) break;
    size_t prefix = (size_t)(hit - cur);
    memcpy(out + wi, cur, prefix);
    wi += prefix;
    memcpy(out + wi, replacement, r_len);
    wi += r_len;
    cur = hit + p_len;
  }
  size_t tail = strlen(cur);
  memcpy(out + wi, cur, tail);
  wi += tail;
  out[wi] = '\0';
  return (uintptr_t)out;
}

uintptr_t __str_split_impl(uintptr_t s_ptr, uintptr_t delimiter_ptr) {
  const char *s = (const char *)s_ptr;
  const char *delimiter = (const char *)delimiter_ptr;
  if (s == NULL) s = "";
  if (delimiter == NULL || delimiter[0] == '\0') {
    char *only = astra_strdup_s(s);
    char *items[1] = {only};
    return astra_make_vec_str(items, 1);
  }

  size_t d_len = strlen(delimiter);
  size_t cap = 8;
  size_t len = 0;
  char **items = (char **)malloc(cap * sizeof(char *));
  if (items == NULL) return astra_make_vec_str(NULL, 0);

  const char *cur = s;
  while (true) {
    const char *hit = strstr(cur, delimiter);
    if (hit == NULL) break;
    if (len == cap) {
      cap *= 2;
      char **grown = (char **)realloc(items, cap * sizeof(char *));
      if (grown == NULL) {
        free(items);
        return astra_make_vec_str(NULL, 0);
      }
      items = grown;
    }
    items[len++] = astra_substr_copy(cur, 0, (size_t)(hit - cur));
    cur = hit + d_len;
  }
  if (len == cap) {
    cap += 1;
    char **grown = (char **)realloc(items, cap * sizeof(char *));
    if (grown == NULL) {
      free(items);
      return astra_make_vec_str(NULL, 0);
    }
    items = grown;
  }
  items[len++] = astra_strdup_s(cur);
  uintptr_t out = astra_make_vec_str(items, len);
  free(items);
  return out;
}

uintptr_t __str_join_impl(uintptr_t parts_ptr, uintptr_t delimiter_ptr) {
  const char *delimiter = (const char *)delimiter_ptr;
  if (delimiter == NULL) delimiter = "";
  if (parts_ptr == 0) return (uintptr_t)astra_strdup_s("");
  AstraRuntimeVecHeader *hdr = (AstraRuntimeVecHeader *)parts_ptr;
  size_t n = (size_t)hdr->len;
  char **parts = (char **)hdr->data;
  if (n == 0 || parts == NULL) return (uintptr_t)astra_strdup_s("");

  size_t d_len = strlen(delimiter);
  size_t total = 0;
  for (size_t i = 0; i < n; i++) {
    total += strlen(parts[i] ? parts[i] : "");
    if (i + 1 < n) total += d_len;
  }
  char *out = (char *)astra_heap_alloc(total + 1);
  if (out == NULL) return (uintptr_t)astra_strdup_s("");
  size_t wi = 0;
  for (size_t i = 0; i < n; i++) {
    const char *p = parts[i] ? parts[i] : "";
    size_t pl = strlen(p);
    memcpy(out + wi, p, pl);
    wi += pl;
    if (i + 1 < n && d_len > 0) {
      memcpy(out + wi, delimiter, d_len);
      wi += d_len;
    }
  }
  out[wi] = '\0';
  return (uintptr_t)out;
}

uintptr_t __string_to_utf8_impl(uintptr_t s_ptr) {
  const char *s = (const char *)s_ptr;
  if (s == NULL) return astra_make_vec_u8(NULL, 0);
  return astra_make_vec_u8((const uint8_t *)s, strlen(s));
}

uintptr_t __utf8_to_string_impl(uintptr_t bytes_ptr) {
  const uint8_t *data = NULL;
  size_t len = 0;
  if (!astra_read_vec_u8(bytes_ptr, &data, &len) || data == NULL) return (uintptr_t)astra_strdup_s("");
  char *out = (char *)astra_heap_alloc(len + 1);
  if (out == NULL) return (uintptr_t)astra_strdup_s("");
  memcpy(out, data, len);
  out[len] = '\0';
  return (uintptr_t)out;
}

uintptr_t __bytes_to_hex_impl(uintptr_t bytes_ptr) {
  const uint8_t *data = NULL;
  size_t len = 0;
  if (!astra_read_vec_u8(bytes_ptr, &data, &len)) return (uintptr_t)astra_strdup_s("");
  static const char *hex = "0123456789abcdef";
  char *out = (char *)astra_heap_alloc(len * 2 + 1);
  if (out == NULL) return (uintptr_t)astra_strdup_s("");
  for (size_t i = 0; i < len; i++) {
    uint8_t b = data ? data[i] : 0;
    out[i * 2 + 0] = hex[(b >> 4) & 0xF];
    out[i * 2 + 1] = hex[b & 0xF];
  }
  out[len * 2] = '\0';
  return (uintptr_t)out;
}

uintptr_t __bytes_to_hex_upper_impl(uintptr_t bytes_ptr) {
  const uint8_t *data = NULL;
  size_t len = 0;
  if (!astra_read_vec_u8(bytes_ptr, &data, &len)) return (uintptr_t)astra_strdup_s("");
  static const char *hex = "0123456789ABCDEF";
  char *out = (char *)astra_heap_alloc(len * 2 + 1);
  if (out == NULL) return (uintptr_t)astra_strdup_s("");
  for (size_t i = 0; i < len; i++) {
    uint8_t b = data ? data[i] : 0;
    out[i * 2 + 0] = hex[(b >> 4) & 0xF];
    out[i * 2 + 1] = hex[b & 0xF];
  }
  out[len * 2] = '\0';
  return (uintptr_t)out;
}

uintptr_t __hex_to_bytes_impl(uintptr_t hex_ptr) {
  const char *s = (const char *)hex_ptr;
  if (s == NULL) return astra_make_vec_u8(NULL, 0);
  size_t n = strlen(s);
  if ((n % 2) != 0) return 0;
  uint8_t *tmp = (uint8_t *)malloc(n / 2);
  if (tmp == NULL && n > 0) return 0;
  for (size_t i = 0; i < n; i += 2) {
    int hi = astra_hex_nibble(s[i]);
    int lo = astra_hex_nibble(s[i + 1]);
    if (hi < 0 || lo < 0) {
      free(tmp);
      return 0;
    }
    tmp[i / 2] = (uint8_t)((hi << 4) | lo);
  }
  uintptr_t out = astra_make_vec_u8(tmp, n / 2);
  free(tmp);
  return out;
}

static const char *ASTRA_B64_TABLE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

uintptr_t __bytes_to_base64_impl(uintptr_t bytes_ptr) {
  const uint8_t *data = NULL;
  size_t len = 0;
  if (!astra_read_vec_u8(bytes_ptr, &data, &len)) return (uintptr_t)astra_strdup_s("");
  if (len == 0) return (uintptr_t)astra_strdup_s("");
  size_t out_len = 4 * ((len + 2) / 3);
  char *out = (char *)astra_heap_alloc(out_len + 1);
  if (out == NULL) return (uintptr_t)astra_strdup_s("");
  size_t i = 0;
  size_t j = 0;
  while (i < len) {
    size_t rem = len - i;
    uint32_t oct0 = data[i++];
    uint32_t oct1 = rem > 1 ? data[i++] : 0;
    uint32_t oct2 = rem > 2 ? data[i++] : 0;
    uint32_t triple = (oct0 << 16) | (oct1 << 8) | oct2;
    out[j++] = ASTRA_B64_TABLE[(triple >> 18) & 0x3F];
    out[j++] = ASTRA_B64_TABLE[(triple >> 12) & 0x3F];
    out[j++] = rem > 1 ? ASTRA_B64_TABLE[(triple >> 6) & 0x3F] : '=';
    out[j++] = rem > 2 ? ASTRA_B64_TABLE[triple & 0x3F] : '=';
  }
  out[out_len] = '\0';
  return (uintptr_t)out;
}

static int astra_b64_inv(char ch) {
  if (ch >= 'A' && ch <= 'Z') return ch - 'A';
  if (ch >= 'a' && ch <= 'z') return 26 + (ch - 'a');
  if (ch >= '0' && ch <= '9') return 52 + (ch - '0');
  if (ch == '+') return 62;
  if (ch == '/') return 63;
  if (ch == '=') return -2;
  return -1;
}

uintptr_t __base64_to_bytes_impl(uintptr_t base64_ptr) {
  const char *s = (const char *)base64_ptr;
  if (s == NULL) return astra_make_vec_u8(NULL, 0);
  size_t n = strlen(s);
  if (n % 4 != 0) return 0;
  size_t max_out = (n / 4) * 3;
  uint8_t *tmp = (uint8_t *)malloc(max_out > 0 ? max_out : 1);
  if (tmp == NULL) return 0;
  size_t wi = 0;
  for (size_t i = 0; i < n; i += 4) {
    int a = astra_b64_inv(s[i + 0]);
    int b = astra_b64_inv(s[i + 1]);
    int c = astra_b64_inv(s[i + 2]);
    int d = astra_b64_inv(s[i + 3]);
    if (a < 0 || b < 0 || c == -1 || d == -1) {
      free(tmp);
      return 0;
    }
    uint32_t triple = ((uint32_t)a << 18) | ((uint32_t)b << 12) | ((uint32_t)(c < 0 ? 0 : c) << 6) |
                      (uint32_t)(d < 0 ? 0 : d);
    tmp[wi++] = (uint8_t)((triple >> 16) & 0xFF);
    if (c != -2) tmp[wi++] = (uint8_t)((triple >> 8) & 0xFF);
    if (d != -2) tmp[wi++] = (uint8_t)(triple & 0xFF);
    if ((c == -2 || d == -2) && i + 4 != n) {
      free(tmp);
      return 0;
    }
  }
  uintptr_t out = astra_make_vec_u8(tmp, wi);
  free(tmp);
  return out;
}

uintptr_t __url_encode_impl(uintptr_t s_ptr) {
  const char *s = (const char *)s_ptr;
  if (s == NULL) return (uintptr_t)astra_strdup_s("");
  size_t n = strlen(s);
  size_t max = n * 3 + 1;
  char *out = (char *)astra_heap_alloc(max);
  if (out == NULL) return (uintptr_t)astra_strdup_s("");
  size_t wi = 0;
  static const char *hex = "0123456789ABCDEF";
  for (size_t i = 0; i < n; i++) {
    unsigned char ch = (unsigned char)s[i];
    if (astra_url_unreserved(ch)) {
      out[wi++] = (char)ch;
    } else {
      out[wi++] = '%';
      out[wi++] = hex[(ch >> 4) & 0xF];
      out[wi++] = hex[ch & 0xF];
    }
  }
  out[wi] = '\0';
  return (uintptr_t)out;
}

uintptr_t __url_decode_impl(uintptr_t encoded_ptr) {
  const char *s = (const char *)encoded_ptr;
  if (s == NULL) return (uintptr_t)astra_strdup_s("");
  size_t n = strlen(s);
  char *out = (char *)astra_heap_alloc(n + 1);
  if (out == NULL) return 0;
  size_t wi = 0;
  for (size_t i = 0; i < n; i++) {
    if (s[i] == '%') {
      if (i + 2 >= n) return 0;
      int hi = astra_hex_nibble(s[i + 1]);
      int lo = astra_hex_nibble(s[i + 2]);
      if (hi < 0 || lo < 0) return 0;
      out[wi++] = (char)((hi << 4) | lo);
      i += 2;
    } else {
      out[wi++] = s[i];
    }
  }
  out[wi] = '\0';
  return (uintptr_t)out;
}
