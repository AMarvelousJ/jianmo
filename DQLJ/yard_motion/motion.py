import math


class Axis:
    def __init__(self, config):
        self.config = config
        self.reset()

    def reset(self):
        self.position = self.config["initial"]
        self.velocity = 0.0
        self.target = None
        self.mode = "idle"
        self.requested_speed = 0.0
        self.jog_deadline = 0.0

    def stop(self, immediate=False):
        self.target = None
        self.requested_speed = 0.0
        self.mode = "stopping" if self.velocity and not immediate else "idle"
        if immediate:
            self.velocity = 0.0

    def set_target(self, value, speed_limit=None):
        self.target = value
        self.mode = "target"
        self.requested_speed = self.config["max_speed"] if speed_limit is None else speed_limit

    def jog(self, speed, deadline):
        self.target = None
        self.mode = "jog"
        self.requested_speed = speed
        self.jog_deadline = deadline

    def update(self, dt):
        remaining = dt
        while remaining > 1e-10:
            h = min(remaining, .002)
            remaining -= h
            self._step(h)

    def _step(self, dt):
        c = self.config
        old = self.velocity
        speed = abs(old)
        duration = dt
        acceleration = 0.0
        goal = self.target if self.mode == "target" else (
            c["maximum"] if self.requested_speed > 0 else c["minimum"])
        distance = goal - self.position
        direction = 1 if distance > 0 else -1
        max_speed = min(c["max_speed"], abs(self.requested_speed))
        braking = self.mode not in ("target", "jog") or old * distance < 0 or (
            speed > 0 and abs(distance) <= speed * speed / (2 * c["deceleration"]) + 1e-9)
        if braking:
            if speed:
                acceleration = -math.copysign(c["deceleration"], old)
                duration = min(dt, speed / c["deceleration"])
        elif abs(distance) > c["tolerance"] or speed:
            peak = min(max_speed, math.sqrt((2 * c["acceleration"] * c["deceleration"] * abs(distance)
                       + c["deceleration"] * speed * speed) / (c["acceleration"] + c["deceleration"])))
            if speed > peak + 1e-8:
                acceleration = -direction * c["deceleration"]
                duration = min(dt, (speed - peak) / c["deceleration"])
            elif speed < peak - 1e-8:
                acceleration = direction * c["acceleration"]
                duration = min(dt, (peak - speed) / c["acceleration"])
            elif speed:
                cruise = (abs(distance) - speed * speed / (2 * c["deceleration"])) / speed
                if cruise > 1e-8:
                    duration = min(dt, cruise)
                else:
                    acceleration = -direction * c["deceleration"]
                    duration = min(dt, speed / c["deceleration"])
        self.position += old * duration + .5 * acceleration * duration * duration
        self.velocity = old + acceleration * duration
        if abs(self.velocity) < 1e-9:
            self.velocity = 0.0
        self.position = max(c["minimum"], min(c["maximum"], self.position))
        if self.mode == "target" and abs(self.position - goal) <= c["tolerance"] and not self.velocity:
            self.position = goal
            self.stop(True)
        elif self.mode == "jog" and abs(self.position - goal) < 1e-8 and not self.velocity:
            self.position = goal
            self.stop(True)
        elif self.mode == "stopping" and not self.velocity:
            self.mode = "idle"
        if duration < dt - 1e-9:
            self._step(dt - duration)

    def state(self):
        return dict(position=self.position, velocity=self.velocity, target=self.target, mode=self.mode,
                    at_target=self.mode == "idle", at_min=self.position <= self.config["minimum"],
                    at_max=self.position >= self.config["maximum"])


class Drive:
    def __init__(self, config, phase_factor):
        self.config = config
        self.phase_factor = phase_factor
        self.reset()

    def reset(self):
        self.speed = self.target_speed = self.distance = 0.0

    def stop(self, immediate=False):
        self.target_speed = 0.0
        if immediate:
            self.speed = 0.0

    def update(self, dt):
        old = self.speed
        rate = self.config["acceleration" if self.target_speed > old else "deceleration"]
        self.speed += max(-rate * dt, min(rate * dt, self.target_speed - old))
        ramp_time = abs(self.speed - old) / rate
        self.distance += ((old + self.speed) * .5 * ramp_time + self.speed * (dt - ramp_time)) * self.phase_factor

    def state(self):
        return dict(speed=self.speed, target_speed=self.target_speed, distance=self.distance,
                    phase=self.distance % 360 if self.phase_factor == 6 else 0)
