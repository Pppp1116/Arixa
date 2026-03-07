# Geometry Module

The `std.geometry` module provides 2D/3D vector and matrix operations for graphics, physics, and computational geometry. All operations are pure and work in both hosted and freestanding modes.

## Usage

```astra
import std.geometry;
```

## 2D Vector Operations

### Creating Vectors

#### `vec2(x: Float, y: Float) -> Vec2`

Create a new 2D vector.

**Example:**
```astra
v = vec2(3.0, 4.0);
```

#### `vec2_zero() -> Vec2`

Create a zero vector (0, 0).

#### `vec2_one() -> Vec2`

Create a unit vector (1, 1).

#### `vec2_unit_x() -> Vec2` / `vec2_unit_y() -> Vec2`

Create unit vectors along axes.

**Example:**
```astra
zero = vec2_zero();           // (0, 0)
one = vec2_one();             // (1, 1)
x_axis = vec2_unit_x();       // (1, 0)
y_axis = vec2_unit_y();       // (0, 1)
```

### Basic Operations

#### `vec2_add(a: Vec2, b: Vec2) -> Vec2`

Vector addition.

#### `vec2_sub(a: Vec2, b: Vec2) -> Vec2`

Vector subtraction.

#### `vec2_mul(v: Vec2, scalar: Float) -> Vec2`

Scalar multiplication.

#### `vec2_div(v: Vec2, scalar: Float) -> Vec2`

Scalar division.

**Example:**
```astra
a = vec2(1.0, 2.0);
b = vec2(3.0, 4.0);

sum = vec2_add(a, b);        // (4.0, 6.0)
diff = vec2_sub(b, a);       // (2.0, 2.0)
scaled = vec2_mul(a, 2.0);   // (2.0, 4.0)
```

### Vector Products

#### `vec2_dot(a: Vec2, b: Vec2) -> Float`

Dot product (scalar).

#### `vec2_cross(a: Vec2, b: Vec2) -> Float`

Cross product (returns scalar for 2D).

**Example:**
```astra
a = vec2(1.0, 0.0);
b = vec2(0.0, 1.0);

dot = vec2_dot(a, b);        // 0.0
cross = vec2_cross(a, b);    // 1.0
```

### Magnitude and Normalization

#### `vec2_magnitude(v: Vec2) -> Float`

Vector length (magnitude).

#### `vec2_magnitude_squared(v: Vec2) -> Float`

Squared magnitude (avoids square root).

#### `vec2_normalize(v: Vec2) -> Vec2`

Unit vector in same direction.

**Example:**
```astra
v = vec2(3.0, 4.0);
length = vec2_magnitude(v);        // 5.0
length_sq = vec2_magnitude_squared(v); // 25.0
unit = vec2_normalize(v);           // (0.6, 0.8)
```

### Distance and Interpolation

#### `vec2_distance(a: Vec2, b: Vec2) -> Float`

Distance between two vectors.

#### `vec2_lerp(a: Vec2, b: Vec2, t: Float) -> Vec2`

Linear interpolation between vectors.

**Example:**
```astra
a = vec2(0.0, 0.0);
b = vec2(10.0, 10.0);

dist = vec2_distance(a, b);  // 14.142...
midpoint = vec2_lerp(a, b, 0.5);  // (5.0, 5.0)
```

### Angle and Rotation

#### `vec2_angle(v: Vec2) -> Float`

Vector angle in radians.

#### `vec2_from_angle(angle: Float) -> Vec2`

Create unit vector from angle.

#### `vec2_rotate(v: Vec2, angle: Float) -> Vec2`

Rotate vector by angle (radians).

**Example:**
```astra
v = vec2(1.0, 0.0);
angle = vec2_angle(v);        // 0.0

rotated = vec2_rotate(v, PI/2); // (0.0, 1.0)
```

## 3D Vector Operations

### Creating Vectors

#### `vec3(x: Float, y: Float, z: Float) -> Vec3`

Create a new 3D vector.

#### `vec3_zero() -> Vec3`
#### `vec3_one() -> Vec3`
#### `vec3_unit_x() -> Vec3`
#### `vec3_unit_y() -> Vec3`
#### `vec3_unit_z() -> Vec3`

**Example:**
```astra
v = vec3(1.0, 2.0, 3.0);
unit_z = vec3_unit_z();  // (0, 0, 1)
```

### Basic Operations

Same operations as 2D vectors but for 3D:

- `vec3_add`, `vec3_sub`, `vec3_mul`, `vec3_div`
- `vec3_dot`, `vec3_cross`
- `vec3_magnitude`, `vec3_normalize`
- `vec3_distance`, `vec3_lerp`

**Example:**
```astra
a = vec3(1.0, 0.0, 0.0);
b = vec3(0.0, 1.0, 0.0);

cross = vec3_cross(a, b);  // (0, 0, 1)
```

## Matrix Operations (4x4)

### Creating Matrices

#### `mat4_identity() -> Mat4`

Create identity matrix.

#### `mat4_translation(x: Float, y: Float, z: Float) -> Mat4`

Create translation matrix.

#### `mat4_scale(x: Float, y: Float, z: Float) -> Mat4`

Create scaling matrix.

#### `mat4_rotation_x(angle: Float) -> Mat4`
#### `mat4_rotation_y(angle: Float) -> Mat4`
#### `mat4_rotation_z(angle: Float) -> Mat4`

Create rotation matrices (angle in radians).

**Example:**
```astra
identity = mat4_identity();
translate = mat4_translation(5.0, 0.0, 0.0);
scale = mat4_scale(2.0, 2.0, 2.0);
rotate_x = mat4_rotation_x(PI/4);
```

### Matrix Operations

#### `mat4_mul(a: Mat4, b: Mat4) -> Mat4`

Matrix multiplication.

#### `mat4_transform_point(m: Mat4, point: Vec3) -> Vec3`

Transform 3D point by matrix.

#### `mat4_transform_direction(m: Mat4, dir: Vec3) -> Vec3`

Transform 3D direction (ignores translation).

**Example:**
```astra
transform = mat4_mul(translate, rotate_x);
point = vec3(1.0, 2.0, 3.0);
transformed = mat4_transform_point(transform, point);
```

## Geometric Calculations

### Point-to-Line Distance

#### `point_to_line_distance_2d(point: Vec2, line_start: Vec2, line_end: Vec2) -> Float`

Calculate distance from point to line segment (2D).

**Example:**
```astra
point = vec2(0.0, 5.0);
line_start = vec2(0.0, 0.0);
line_end = vec2(10.0, 0.0);

distance = point_to_line_distance_2d(point, line_start, line_end); // 5.0
```

### Triangle Operations

#### `point_in_triangle_2d(point: Vec2, a: Vec2, b: Vec2, c: Vec2) -> Bool`

Check if point is inside triangle (2D).

#### `triangle_area_2d(a: Vec2, b: Vec2, c: Vec2) -> Float`

Calculate triangle area (2D).

#### `circle_from_three_points_2d(a: Vec2, b: Vec2, c: Vec2) -> (Vec2, Float)?`

Calculate circle center and radius from three points (2D).

**Example:**
```astra
a = vec2(0.0, 0.0);
b = vec2(1.0, 0.0);
c = vec2(0.5, 0.866);  // Equilateral triangle

area = triangle_area_2d(a, b, c);  // 0.433...

circle_result = circle_from_three_points_2d(a, b, c);
if circle_result != none {
    center = (circle_result as (Vec2, Float)?).0;
    radius = (circle_result as (Vec2, Float)?).1;
}
```

### Bounding Box

#### `bounding_box_2d(points: Vec<Vec2>) -> (Vec2, Vec2)?`

Calculate axis-aligned bounding box for points (2D).

**Returns:** (min_point, max_point) or `none` if no points

**Example:**
```astra
points = vec_from([
    vec2(1.0, 2.0),
    vec2(3.0, 4.0),
    vec2(5.0, 1.0)
]);

bbox = bounding_box_2d(points);
if bbox != none {
    min = (bbox as (Vec2, Vec2)?).0;
    max = (bbox as (Vec2, Vec2)?).1;
    // min = (1.0, 1.0), max = (5.0, 4.0)
}
```

## Utility Functions

### Constants

```astra
const PI = 3.14159265358979323846;
const PI_2 = 1.57079632679489661923;  // PI / 2
const PI_4 = 0.78539816339744830962;  // PI / 4
const TWO_PI = 6.28318530717958647692; // 2 * PI
const EPSILON = 1e-6;
```

### Conversions

#### `deg_to_rad(degrees: Float) -> Float`

Convert degrees to radians.

#### `rad_to_deg(radians: Float) -> Float`

Convert radians to degrees.

**Example:**
```astra
rad = deg_to_rad(180.0);  // PI
deg = rad_to_deg(PI);     // 180.0
```

### Interpolation

#### `lerp(a: Float, b: Float, t: Float) -> Float`

Linear interpolation between values.

#### `smooth_step(edge0: Float, edge1: Float, x: Float) -> Float`

Smooth step interpolation.

**Example:**
```astra
mid = lerp(0.0, 10.0, 0.5);  // 5.0
smooth = smooth_step(0.0, 1.0, 0.5);  // 0.5
```

#### `clamp(value: Float, min: Float, max: Float) -> Float`

Clamp value between min and max.

## Usage Examples

### 2D Physics Simulation

```astra
import std.geometry;

struct Particle {
    position Vec2,
    velocity Vec2,
    mass Float,
}

fn update_particle(particle &mut Particle, dt Float, gravity Vec2) {
    // Apply gravity
    particle.velocity = vec2_add(particle.velocity, vec2_mul(gravity, dt));
    
    // Update position
    particle.position = vec2_add(particle.position, vec2_mul(particle.velocity, dt));
    
    // Apply damping
    particle.velocity = vec2_mul(particle.velocity, 0.99);
}

fn check_collision(p1 Particle, p2 Particle) Bool {
    distance = vec2_distance(p1.position, p2.position);
    return distance < 10.0;  // Collision radius
}

// Usage
mut particle1 = Particle{vec2(0.0, 0.0), vec2(1.0, 0.0), 1.0};
mut particle2 = Particle{vec2(50.0, 0.0), vec2(-1.0, 0.0), 1.0};
gravity = vec2(0.0, -9.81);

update_particle(particle1, 0.016, gravity);  // 60 FPS
update_particle(particle2, 0.016, gravity);

if check_collision(particle1, particle2) {
    print("Collision detected!");
}
```

### 3D Transformations

```astra
import std.geometry;

fn create_transform(translation Vec3, rotation Vec3, scale Vec3) Mat4 {
    // Create individual transforms
    t = mat4_translation(translation.x, translation.y, translation.z);
    rx = mat4_rotation_x(rotation.x);
    ry = mat4_rotation_y(rotation.y);
    rz = mat4_rotation_z(rotation.z);
    s = mat4_scale(scale.x, scale.y, scale.z);
    
    // Combine rotations
    r = mat4_mul(rz, mat4_mul(ry, rx));
    
    // Combine all transforms
    return mat4_mul(t, mat4_mul(r, s));
}

fn transform_point(transform Mat4, point Vec3) Vec3 {
    return mat4_transform_point(transform, point);
}

// Usage
transform = create_transform(
    vec3(10.0, 5.0, 0.0),  // Translation
    vec3(0.0, PI/4, 0.0),   // Rotation
    vec3(2.0, 2.0, 2.0)     // Scale
);

original_point = vec3(1.0, 1.0, 1.0);
transformed_point = transform_point(transform, original_point);
```

### Collision Detection

```astra
import std.geometry;

fn point_in_circle(point Vec2, center Vec2, radius Float) Bool {
    distance = vec2_distance(point, center);
    return distance <= radius;
}

fn line_circle_intersection(line_start Vec2, line_end Vec2, circle_center Vec2, circle_radius Float) Bool {
    distance = point_to_line_distance_2d(circle_center, line_start, line_end);
    return distance <= circle_radius;
}

fn triangle_circle_collision(triangle_a Vec2, triangle_b Vec2, triangle_c Vec2, circle_center Vec2, circle_radius Float) Bool {
    // Check if circle center is inside triangle
    if point_in_triangle_2d(circle_center, triangle_a, triangle_b, triangle_c) {
        return true;
    }
    
    // Check distance from circle center to triangle edges
    dist1 = point_to_line_distance_2d(circle_center, triangle_a, triangle_b);
    dist2 = point_to_line_distance_2d(circle_center, triangle_b, triangle_c);
    dist3 = point_to_line_distance_2d(circle_center, triangle_c, triangle_a);
    
    return dist1 <= circle_radius || dist2 <= circle_radius || dist3 <= circle_radius;
}

// Usage
circle_center = vec2(50.0, 50.0);
circle_radius = 10.0;

triangle = vec_from([
    vec2(40.0, 40.0),
    vec2(60.0, 40.0),
    vec2(50.0, 60.0)
]);

collides = triangle_circle_collision(
    triangle[0], triangle[1], triangle[2],
    circle_center, circle_radius
);
```

### Path Planning

```astra
import std.geometry;

fn find_path(start Vec2, end Vec2, obstacles Vec<Vec2>) Vec<Vec2>? {
    // Simple path planning - avoid obstacles by going around them
    mut path = vec_from([start]);
    current = start;
    
    while vec2_distance(current, end) > 1.0 {
        direction = vec2_normalize(vec2_sub(end, current));
        next_point = vec2_add(current, vec2_mul(direction, 5.0));
        
        // Check for collision with obstacles
        mut collision = false;
        mut i = 0;
        while i < vec_len(obstacles) {
            obstacle_opt = vec_get(obstacles, i);
            if obstacle_opt != none {
                obstacle = (obstacle_opt as Vec2?) ?? vec2_zero();
                if vec2_distance(next_point, obstacle) < 3.0 {
                    collision = true;
                    break;
                }
            }
            i += 1;
        }
        
        if collision {
            // Try to go around obstacle
            perpendicular = Vec2{-direction.y, direction.x};
            next_point = vec2_add(current, vec2_mul(perpendicular, 5.0));
        }
        
        vec_push(path, next_point);
        current = next_point;
    }
    
    vec_push(path, end);
    return path;
}

// Usage
start_point = vec2(0.0, 0.0);
end_point = vec2(100.0, 100.0);
obstacles = vec_from([
    vec2(50.0, 50.0),
    vec2(25.0, 75.0),
    vec2(75.0, 25.0)
]);

path = find_path(start_point, end_point, obstacles);
```

## Performance Considerations

### Vector Operations

- **Magnitude vs Squared Magnitude:** Use squared magnitude for comparisons to avoid square root
- **Normalization:** Consider caching normalized vectors if used frequently
- **Dot Product:** Faster than cross product for simple comparisons

### Matrix Operations

- **Matrix Multiplication:** Expensive operation, cache results when possible
- **Transformations:** Combine multiple transforms into single matrix
- **Memory Layout:** Consider memory layout for large batches of operations

### Geometric Algorithms

- **Bounding Boxes:** Use for broad-phase collision detection
- **Spatial Partitioning:** Consider for large numbers of objects
- **Approximation:** Use approximations for real-time applications

## Freestanding Compatibility

✅ **Freestanding-safe** - All operations are pure mathematical computations that don't require runtime support.

## See Also

- [Math Module](math.md) - Basic mathematical functions
- [Random Module](random.md) - Random number generation for simulations
- [Hardware Module](hardware.md) - Low-level bit operations
