"""The Studio-side player: bodies, camera, props, effects, faces and lines.

The animations carry their own events. A ``KeyframeMarker`` written into an
actor's clip fires ``GetMarkerReachedSignal`` at the exact frame it sits on, so
a gunshot lands with the hand rather than near it — and it keeps doing so after
the clip is published, or retimed in Studio, because the marker travels inside
the animation rather than beside it.

Events with no actor have no clip to ride. Camera cuts and world effects go on
a director clock instead, which is a plain elapsed-time loop started with the
tracks.

Everything the scene names but cannot create — prop models, particle effects,
the wall — is looked up by name and *reported* when missing. A cinematic that
half-plays because one folder is empty is worse than one that says which folder.
"""

from __future__ import annotations

BODY = '''\
local RunService = game:GetService("RunService")
local TweenService = game:GetService("TweenService")
local KeyframeSequenceProvider = game:GetService("KeyframeSequenceProvider")

-- "ServerStorage.LinenAnimations" and friends. The first segment may be a
-- service, which is not a child of game until it exists.
local function resolve(path: string): Instance?
\tlocal current: Instance = game
\tfor segment in string.gmatch(path, "[^%.]+") do
\t\tlocal child: Instance? = current:FindFirstChild(segment)
\t\tif child == nil and current == game then
\t\t\tlocal ok, service = pcall(game.GetService, game, segment)
\t\t\tif ok then
\t\t\t\tchild = service
\t\t\tend
\t\tend
\t\tif child == nil then
\t\t\treturn nil
\t\tend
\t\tcurrent = child
\tend
\treturn current
end

local missing: { string } = {}
local function require_(instance: Instance?, what: string): Instance?
\tif instance == nil then
\t\ttable.insert(missing, what)
\tend
\treturn instance
end

local folder = require_(resolve(FOLDER_PATH), FOLDER_PATH)
local camera = workspace.CurrentCamera

-- ---------------------------------------------------------------- staging --
local models: { [string]: Model } = {}
local tracks: { AnimationTrack } = {}

for _, entry in STAGE do
\tlocal model = workspace:FindFirstChild(entry.name)
\tif model == nil or not model:IsA("Model") then
\t\ttable.insert(missing, `rig "{entry.name}" dans Workspace`)
\t\tcontinue
\tend
\tmodels[entry.name] = model

\tlocal look = entry.position
\tif typeof(entry.facing) == "string" then
\t\tlocal other = workspace:FindFirstChild(entry.facing)
\t\tif other and other:IsA("Model") then
\t\t\tlook = other:GetPivot().Position
\t\tend
\telseif typeof(entry.facing) == "number" then
\t\tlook = entry.position
\t\t\t+ Vector3.new(math.sin(math.rad(entry.facing)), 0, -math.cos(math.rad(entry.facing)))
\tend

\tif look ~= entry.position then
\t\tmodel:PivotTo(CFrame.lookAt(entry.position, Vector3.new(look.X, entry.position.Y, look.Z)))
\telse
\t\tmodel:PivotTo(CFrame.new(entry.position))
\tend
end

-- ------------------------------------------------------------------ props --
local heldWelds: { [string]: WeldConstraint } = {}

local function propModel(name: string): BasePart?
\tfor _, prop in PROPS do
\t\tif prop.name ~= name then
\t\t\tcontinue
\t\tend
\t\tlocal existing = workspace:FindFirstChild("Linen_" .. name)
\t\tif existing and existing:IsA("BasePart") then
\t\t\treturn existing
\t\tend
\t\tlocal source = resolve(prop.source)
\t\tif source == nil then
\t\t\ttable.insert(missing, prop.source)
\t\t\treturn nil
\t\tend
\t\tlocal clone = source:Clone()
\t\tlocal part = if clone:IsA("BasePart") then clone else clone:FindFirstChildWhichIsA("BasePart")
\t\tif part == nil then
\t\t\ttable.insert(missing, `{prop.source} ne contient aucune BasePart`)
\t\t\treturn nil
\t\tend
\t\tclone.Name = "Linen_" .. name
\t\tclone.Parent = workspace
\t\treturn part
\tend
\treturn nil
end

local function attachProp(name: string, actorName: string)
\tlocal part = propModel(name)
\tlocal model = models[actorName]
\tif part == nil or model == nil then
\t\treturn
\tend
\tfor _, prop in PROPS do
\t\tif prop.name == name then
\t\t\tlocal hand = model:FindFirstChild(prop.attachTo)
\t\t\tif hand == nil or not hand:IsA("BasePart") then
\t\t\t\ttable.insert(missing, `{actorName}.{prop.attachTo}`)
\t\t\t\treturn
\t\t\tend
\t\t\tpart.CFrame = hand.CFrame * CFrame.new(prop.grip)
\t\t\tpart.Anchored = false
\t\t\tlocal weld = Instance.new("WeldConstraint")
\t\t\tweld.Part0 = hand
\t\t\tweld.Part1 = part
\t\t\tweld.Parent = part
\t\t\theldWelds[name] = weld
\t\t\treturn
\t\tend
\tend
end

local function releaseProp(name: string, impulse: Vector3?)
\tlocal weld = heldWelds[name]
\tif weld then
\t\tweld:Destroy()
\t\theldWelds[name] = nil
\tend
\tlocal part = workspace:FindFirstChild("Linen_" .. name)
\tif part and part:IsA("BasePart") then
\t\tpart.Anchored = false
\t\tif impulse then
\t\t\t-- Applied as an impulse, so the same numbers the set plan solved the
\t\t\t-- trajectory from are the numbers the engine integrates.
\t\t\tpart:ApplyImpulse(impulse)
\t\tend
\tend
end

-- -------------------------------------------------------------------- vfx --
local function playEffect(effectName: string, atPart: string)
\tlocal host: Instance? = if atPart ~= "" then workspace:FindFirstChild(atPart, true) else nil
\tlocal emitter = workspace:FindFirstChild(effectName, true)
\tif emitter == nil then
\t\ttable.insert(missing, `effet "{effectName}"`)
\t\treturn
\tend
\tif emitter:IsA("ParticleEmitter") then
\t\tif host and host:IsA("BasePart") and emitter.Parent ~= host then
\t\t\tlocal clone = emitter:Clone()
\t\t\tclone.Parent = host
\t\t\tclone:Emit(clone.Rate > 0 and math.ceil(clone.Rate) or 24)
\t\t\ttask.delay(3, function()
\t\t\t\tclone:Destroy()
\t\t\tend)
\t\telse
\t\t\temitter:Emit(24)
\t\tend
\tend
end

-- ------------------------------------------------------------------ sound --
local function playSound(asset: string, volume: number, at: Instance?)
\tif asset == "" or asset == "rbxassetid://0" then
\t\ttable.insert(missing, "un identifiant audio est encore à 0")
\t\treturn
\tend
\tlocal sound = Instance.new("Sound")
\tsound.SoundId = asset
\tsound.Volume = volume
\t-- Parented to a part, Roblox makes it positional on its own.
\tsound.Parent = if at and at:IsA("BasePart") then at else workspace
\tsound:Play()
\tsound.Ended:Once(function()
\t\tsound:Destroy()
\tend)
end

-- ------------------------------------------------------------------ faces --
-- FaceControls is a 50-pose FACS rig on a dynamic head. Named expressions keep
-- a scene readable; a blocky head simply has no FaceControls and is skipped,
-- which is why this never errors.
local function setExpression(actorName: string, name: string, hold: number)
\tlocal model = models[actorName]
\tlocal head = model and model:FindFirstChild("Head")
\tlocal controls = head and head:FindFirstChildOfClass("FaceControls")
\tif controls == nil then
\t\treturn
\tend
\tlocal pose = EXPRESSIONS[name]
\tif pose == nil then
\t\treturn
\tend
\tfor property, value in pose do
\t\tpcall(function()
\t\t\t(controls :: any)[property] = value
\t\tend)
\tend
\tif hold > 0 then
\t\ttask.delay(hold, function()
\t\t\tfor property in pose do
\t\t\t\tpcall(function()
\t\t\t\t\t(controls :: any)[property] = 0
\t\t\t\tend)
\t\t\tend
\t\tend)
\tend
end

-- ------------------------------------------------------------------- line --
local function showLine(actorName: string, text: string, hold: number)
\tlocal model = models[actorName]
\tlocal head = model and model:FindFirstChild("Head")
\tif head == nil or not head:IsA("BasePart") then
\t\tprint(`[{actorName}] {text}`)
\t\treturn
\tend
\tlocal gui = Instance.new("BillboardGui")
\tgui.Size = UDim2.fromScale(12, 2)
\tgui.StudsOffset = Vector3.new(0, 2.5, 0)
\tgui.AlwaysOnTop = true
\tgui.Parent = head

\tlocal label = Instance.new("TextLabel")
\tlabel.Size = UDim2.fromScale(1, 1)
\tlabel.BackgroundTransparency = 1
\tlabel.TextScaled = true
\tlabel.Font = Enum.Font.GothamMedium
\tlabel.TextColor3 = Color3.new(1, 1, 1)
\tlabel.TextStrokeTransparency = 0.4
\tlabel.Text = text
\tlabel.Parent = gui

\ttask.delay(hold, function()
\t\tgui:Destroy()
\tend)
end

-- ----------------------------------------------------------------- camera --
local originalCameraType = camera.CameraType
local function cutTo(shotId: string)
\tfor _, shot in SHOTS do
\t\tif shot.id ~= shotId then
\t\t\tcontinue
\t\tend
\t\tlocal target = workspace:FindFirstChild(shot.lookAt, true)
\t\tlocal focus = if target then target:GetPivot().Position else Vector3.zero
\t\tlocal goal = CFrame.lookAt(shot.position, focus)

\t\tcamera.CameraType = Enum.CameraType.Scriptable
\t\tcamera.FieldOfView = shot.fov
\t\tif shot.blend > 0 then
\t\t\tTweenService:Create(camera, TweenInfo.new(shot.blend, Enum.EasingStyle.Quad), {
\t\t\t\tCFrame = goal,
\t\t\t}):Play()
\t\telse
\t\t\tcamera.CFrame = goal
\t\tend

\t\t-- A perfectly still camera reads as a screenshot, so every shot drifts.
\t\tif shot.drift.Magnitude > 0 then
\t\t\tTweenService:Create(camera, TweenInfo.new(4, Enum.EasingStyle.Linear), {
\t\t\t\tCFrame = CFrame.lookAt(shot.position + shot.drift, focus),
\t\t\t}):Play()
\t\tend
\t\treturn
\tend
end

-- ----------------------------------------------------------------- events --
local function fire(kind: string, value: string, actorName: string?)
\tlocal parts = string.split(value, "|")
\tif kind == "sound" then
\t\tlocal model = if actorName then models[actorName] else nil
\t\tplaySound(parts[1] or "", 1, model and model:FindFirstChild("Head"))
\telseif kind == "vfx" then
\t\tplayEffect(parts[1] or "", parts[2] or "")
\telseif kind == "face" then
\t\tsetExpression(actorName or "", parts[1] or "", tonumber(parts[2]) or 2)
\telseif kind == "line" then
\t\tshowLine(actorName or "", parts[1] or "", tonumber(parts[2]) or 2)
\telseif kind == "camera" then
\t\tcutTo(parts[1] or "")
\telseif kind == "prop" then
\t\tlocal name, action, impulse = parts[1], parts[2], parts[3]
\t\tif action == "attach" then
\t\t\tattachProp(name, actorName or "")
\t\telse
\t\t\tlocal vector: Vector3? = nil
\t\t\tif impulse and impulse ~= "" then
\t\t\t\tlocal n = string.split(impulse, ",")
\t\t\t\tvector = Vector3.new(tonumber(n[1]) or 0, tonumber(n[2]) or 0, tonumber(n[3]) or 0)
\t\t\tend
\t\t\treleaseProp(name, vector)
\t\tend
\tend
end

-- ------------------------------------------------------------------- play --
for _, prop in PROPS do
\tif prop.heldBy ~= nil then
\t\tattachProp(prop.name, prop.heldBy)
\tend
end

for _, entry in STAGE do
\tlocal model = models[entry.name]
\tif model == nil then
\t\tcontinue
\tend
\tlocal humanoid = model:FindFirstChildOfClass("Humanoid")
\tlocal animator = humanoid and humanoid:FindFirstChildOfClass("Animator")
\tif animator == nil then
\t\ttable.insert(missing, `Animator sur "{entry.name}"`)
\t\tcontinue
\tend

\tlocal sequenceName = string.format("%s_%s", SCENE_NAME, entry.name)
\tlocal sequence = folder and folder:FindFirstChild(sequenceName)
\tif sequence == nil or not sequence:IsA("KeyframeSequence") then
\t\ttable.insert(missing, `KeyframeSequence "{sequenceName}"`)
\t\tcontinue
\tend

\tlocal animation = Instance.new("Animation")
\tanimation.Name = sequenceName
\tanimation.AnimationId = KeyframeSequenceProvider:RegisterKeyframeSequence(sequence)

\tlocal track = animator:LoadAnimation(animation)
\ttrack.Priority = Enum.AnimationPriority.Action4
\ttrack.Looped = false

\t-- The clip carries its own events. One connection per kind is enough: the
\t-- marker's value says what to do.
\tfor _, kind in { "sound", "vfx", "face", "line", "prop", "camera" } do
\t\tlocal actorName = entry.name
\t\ttrack:GetMarkerReachedSignal("linen_" .. kind):Connect(function(value: string)
\t\t\tfire(kind, value, actorName)
\t\tend)
\tend

\ttable.insert(tracks, track)
end

if #missing > 0 then
\twarn(`Linen: la scène "{SCENE_NAME}" est incomplète — il manque :`)
\tfor _, item in missing do
\t\twarn(`  - {item}`)
\tend
\twarn("Elle va jouer quand même; ce qui manque sera simplement absent.")
end

-- Every actor starts on the same frame. One track each, all begun together, is
-- the only arrangement that cannot drift over a long take.
for _, track in tracks do
\ttrack:Play(0)
end

-- Events with no actor have no clip to ride, so they run on the director's
-- clock, started with the tracks.
task.spawn(function()
\tlocal elapsed = 0
\tlocal next_ = 1
\twhile next_ <= #DIRECTOR do
\t\telapsed += RunService.Heartbeat:Wait()
\t\twhile next_ <= #DIRECTOR and DIRECTOR[next_].at <= elapsed do
\t\t\tlocal cue = DIRECTOR[next_]
\t\t\tfire(cue.kind, cue.value, cue.actor)
\t\t\tnext_ += 1
\t\tend
\tend
end)

task.delay(DURATION + 1, function()
\tcamera.CameraType = originalCameraType
end)

print(string.format("Linen: %q — %d acteurs, %.2fs, %d cues, %d evenements.",
\tSCENE_NAME, #tracks, DURATION, #CUES, #DIRECTOR))
'''
