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
local SoundService = game:GetService("SoundService")
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
--[[ The camera belongs to the client. On a server `workspace.CurrentCamera`
     is nil, so a scene run from the wrong place would stage its bodies and
     then quietly show nobody anything — the failure with no error. ]]
if not RunService:IsClient() then
\twarn(
\t\t"Linen: cette scene pilote la camera, elle doit tourner cote client. "
\t\t.. "Mets-la dans StarterPlayer > StarterPlayerScripts (LocalScript), "
\t\t.. "ou lance-la depuis la barre de commande de Studio."
\t)
\treturn
end

local camera = workspace.CurrentCamera

-- ---------------------------------------------------------------- staging --
local models: { [string]: Model? } = {}
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
\tif not part or not model then
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
-- Two buses, so the score can duck under the effects and both can be ridden by
-- one number. This is the smallest thing that behaves like a mixer, and every
-- sound below goes through it rather than straight to Workspace.
local sfxBus = Instance.new("SoundGroup")
sfxBus.Name = "LinenSFX"
sfxBus.Volume = 1
sfxBus.Parent = SoundService

local musicBus = Instance.new("SoundGroup")
musicBus.Name = "LinenMusic"
musicBus.Volume = 1
musicBus.Parent = SoundService

-- The tremor. TremoloSoundEffect varies a bus's volume up and down; at low
-- depth it is an unsteadiness you feel rather than hear, which is what a
-- character in trouble should sound like. Depth rides the tension curve.
local tremor = Instance.new("TremoloSoundEffect")
tremor.Frequency = 5.2
tremor.Duty = 0.6
tremor.Depth = 0
tremor.Parent = musicBus

-- And the tunnel: as tension climbs, the top end comes off the world and the
-- bottom swells. It is the oldest trick there is and it works every time.
local tunnel = Instance.new("EqualizerSoundEffect")
tunnel.LowGain = 0
tunnel.MidGain = 0
tunnel.HighGain = 0
tunnel.Parent = sfxBus

local function playSound(asset: string, volume: number, at: Instance?, group: SoundGroup?)
\tif asset == "" or asset == "rbxassetid://0" then
\t\ttable.insert(missing, "un identifiant audio est encore à 0")
\t\treturn
\tend
\tlocal sound = Instance.new("Sound")
\tsound.SoundId = asset
\tsound.Volume = volume
\tsound.SoundGroup = group or sfxBus
\t-- Parented to a part, Roblox makes it positional on its own.
\tsound.Parent = if at and at:IsA("BasePart") then at else workspace
\tsound:Play()
\tsound.Ended:Once(function()
\t\tsound:Destroy()
\tend)
end

-- ----------------------------------------------------------------- spotted --
-- Sounds Linen derived from the animation itself: impacts, footsteps, falls.
-- The intensity travelling with each one is what keeps repeated hits from
-- sounding like a stapler — one sample played at one level is the single most
-- recognisable sign of unfinished game audio.
local function playSpot(slot: string, intensity: number, partName: string, actorName: string?)
\tlocal entry = SOUNDS[slot]
\tif entry == nil or entry.asset == "" then
\t\treturn -- Nothing mapped to this slot yet; the sheet already said so.
\tend

\tlocal host: Instance? = nil
\tlocal model = if actorName then models[actorName] else nil
\tif model and partName ~= "" then
\t\thost = model:FindFirstChild(partName)
\tend
\tif host == nil and partName ~= "" then
\t\thost = workspace:FindFirstChild(partName, true)
\tend

\tlocal sound = Instance.new("Sound")
\tsound.SoundId = entry.asset
\tsound.Volume = entry.volume * (0.45 + 0.55 * intensity)
\t-- Harder hits sit lower, and a little jitter keeps two identical frames
\t-- from sounding identical.
\tsound.PlaybackSpeed = 1.06 - 0.12 * intensity + (math.random() - 0.5) * 0.08
\tsound.SoundGroup = if entry.category == "MUS" then musicBus else sfxBus
\tsound.Parent = if host and host:IsA("BasePart") then host else workspace
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
--[[ The camera is the client's, always. `workspace.CurrentCamera` does not
     exist on a server, so every line below runs in the LocalScript half of
     this scene and the server only says *which* shot to be on. A cinematic
     whose camera code sits on the server plays perfectly in the Command Bar,
     where a local camera happens to exist, and does nothing at all in a real
     game — which is the way this fails without an error. ]]
local activeShot = nil
local shotStartedAt = 0
local shotOrigin = nil

local function subjectOf(shot): Vector3?
\tlocal found = workspace:FindFirstChild(shot.lookAt, true)
\tif found and found:IsA("PVInstance") then
\t\treturn found:GetPivot().Position
\tend
\treturn nil
end

local function cutTo(shotId: string)
\tfor _, shot in SHOTS do
\t\tif shot.id ~= shotId then
\t\t\tcontinue
\t\tend
\t\tactiveShot = shot
\t\tshotStartedAt = os.clock()
\t\tshotOrigin = camera.CFrame
\t\tcamera.CameraType = Enum.CameraType.Scriptable
\t\tcamera.FieldOfView = shot.fov
\t\treturn
\tend
end

--[[ Where the camera should be, this instant. Driven every frame rather than
     tweened to a fixed CFrame, because an orbit and a follow both depend on
     where the subject is *now* — and a subject in a fight does not stay put. ]]
local function poseFor(shot, elapsed: number): CFrame
\tlocal focus = subjectOf(shot) or Vector3.zero

\tif shot.kind == "orbit" then
\t\tlocal flat = Vector3.new(shot.position.X - focus.X, 0, shot.position.Z - focus.Z)
\t\tlocal radius = if shot.orbitRadius > 0 then shot.orbitRadius else flat.Magnitude
\t\tif radius < 0.1 then
\t\t\tradius = 8
\t\tend
\t\tlocal start = math.atan2(flat.Z, flat.X)
\t\tlocal angle = start + math.rad(shot.orbitSpeed) * elapsed
\t\tlocal height = shot.position.Y - focus.Y
\t\tlocal where = focus + Vector3.new(math.cos(angle) * radius, height, math.sin(angle) * radius)
\t\treturn CFrame.lookAt(where, focus)
\tend

\tif shot.kind == "follow" then
\t\treturn CFrame.lookAt(focus + shot.followOffset, focus)
\tend

\tlocal drift = shot.drift * math.clamp(elapsed / 4, 0, 1)
\treturn CFrame.lookAt(shot.position + drift, focus)
end

RunService:BindToRenderStep("LinenCamera", Enum.RenderPriority.Camera.Value, function(delta: number)
\tif activeShot == nil then
\t\treturn
\tend
\tlocal elapsed = os.clock() - shotStartedAt
\tlocal goal = poseFor(activeShot, elapsed)

\t--[[ Two easings, and they are different things. `blend` is the cut itself,
\t     eased over its own length so a change of shot travels instead of
\t     snapping. `followLag` is the operator's hand: a camera welded to its
\t     subject reads as rigid, and a little lag is what makes it look held. ]]
\tif activeShot.blend > 0 and elapsed < activeShot.blend and shotOrigin then
\t\tlocal t = elapsed / activeShot.blend
\t\tcamera.CFrame = shotOrigin:Lerp(goal, t * t * (3 - 2 * t))
\telseif activeShot.kind == "follow" and activeShot.followLag > 0 then
\t\tcamera.CFrame = camera.CFrame:Lerp(goal, math.clamp(delta / activeShot.followLag, 0, 1))
\telse
\t\tcamera.CFrame = goal
\tend
end)

local function releaseCamera()
\tRunService:UnbindFromRenderStep("LinenCamera")
\tactiveShot = nil
\tcamera.CameraType = Enum.CameraType.Custom
end

-- ----------------------------------------------------------------- events --
local function fire(kind: string, value: string, actorName: string?)
\tlocal parts = string.split(value, "|")
\tif kind == "sound" then
\t\tlocal model = if actorName then models[actorName] else nil
\t\tplaySound(parts[1] or "", 1, model and model:FindFirstChild("Head"))
\telseif kind == "spot" then
\t\tplaySpot(parts[1] or "", tonumber(parts[2]) or 1, parts[3] or "", actorName)
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
\tif not model then
\t\tcontinue
\tend
\tlocal humanoid = model:FindFirstChildOfClass("Humanoid")
\tlocal animator = humanoid and humanoid:FindFirstChildOfClass("Animator")
\tif animator == nil then
\t\ttable.insert(missing, `Animator sur "{entry.name}"`)
\t\tcontinue
\tend

\tlocal sequenceName = string.format("%s_%s", SCENE_NAME, entry.name)

\t-- A published id works everywhere, a live server included. Registering a
\t-- KeyframeSequence works only inside Studio, so it is the fallback rather
\t-- than the plan: a scene that plays in Studio and stands still in the game
\t-- is the failure this ordering exists to avoid.
\tlocal assetId = ANIMATION_IDS[entry.name]
\tlocal animation = Instance.new("Animation")
\tanimation.Name = sequenceName

\tif assetId ~= nil and assetId ~= "" then
\t\tanimation.AnimationId = assetId
\telse
\t\tlocal sequence = folder and folder:FindFirstChild(sequenceName)
\t\tif sequence == nil or not sequence:IsA("KeyframeSequence") then
\t\t\ttable.insert(missing, `KeyframeSequence "{sequenceName}", ou son id publie`)
\t\t\tcontinue
\t\tend
\t\tif not RunService:IsStudio() then
\t\t\ttable.insert(missing, `un id publie pour "{entry.name}" — hors Studio une KeyframeSequence ne se joue pas`)
\t\t\tcontinue
\t\tend
\t\tanimation.AnimationId = KeyframeSequenceProvider:RegisterKeyframeSequence(sequence)
\tend

\tlocal track = animator:LoadAnimation(animation)
\ttrack.Priority = Enum.AnimationPriority.Action4
\ttrack.Looped = false

\t-- The clip carries its own events. One connection per kind is enough: the
\t-- marker's value says what to do.
\tfor _, kind in { "sound", "spot", "vfx", "face", "line", "prop", "camera" } do
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

-- --------------------------------------------------------------- ambience --
-- The beds, and the one number they all ride. Linen sampled the scene's
-- tension while spotting it; here that curve becomes volume on the drone, depth
-- on the tremor, and the low-pass that closes in when things get bad. Nothing
-- below is authored frame by frame — it is all the same curve, read live.
local function tensionAt(seconds: number): number
\tif #TENSION == 0 then
\t\treturn 0
\tend
\tlocal last = TENSION[#TENSION]
\tif seconds >= last[1] then
\t\treturn last[2]
\tend
\tfor i = 1, #TENSION - 1 do
\t\tlocal a, b = TENSION[i], TENSION[i + 1]
\t\tif seconds < b[1] then
\t\t\tlocal span = b[1] - a[1]
\t\t\tlocal alpha = if span > 0 then (seconds - a[1]) / span else 0
\t\t\treturn a[2] + (b[2] - a[2]) * alpha
\t\tend
\tend
\treturn last[2]
end

local beds: { { bed: any, sound: Sound } } = {}
for _, bed in AMBIENCE do
\tlocal entry = SOUNDS[bed.slot]
\tif entry == nil or entry.asset == "" then
\t\tcontinue
\tend
\tlocal sound = Instance.new("Sound")
\tsound.SoundId = entry.asset
\tsound.Looped = true
\tsound.Volume = 0
\tsound.SoundGroup = if entry.category == "MUS" then musicBus else sfxBus
\tsound.Parent = SoundService
\ttable.insert(beds, { bed = bed, sound = sound })
end

task.spawn(function()
\tlocal elapsed = 0
\twhile elapsed < DURATION + 1 do
\t\telapsed += RunService.Heartbeat:Wait()
\t\tlocal tension = tensionAt(elapsed)

\t\tfor _, held in beds do
\t\t\tlocal bed, sound = held.bed, held.sound
\t\t\tlocal inside = elapsed >= bed.start and elapsed <= bed.stop
\t\t\tif inside and not sound.IsPlaying then
\t\t\t\tsound:Play()
\t\t\telseif not inside and sound.IsPlaying then
\t\t\t\tsound:Stop()
\t\t\tend
\t\t\tif inside then
\t\t\t\tlocal entry = SOUNDS[bed.slot]
\t\t\t\tlocal reach = bed.low + (bed.high - bed.low) * tension
\t\t\t\t-- Eased rather than set, so a spike in the curve does not click.
\t\t\t\tlocal target = (entry and entry.volume or 0.5) * reach
\t\t\t\tsound.Volume += (target - sound.Volume) * 0.08
\t\t\tend
\t\tend

\t\ttremor.Depth = math.clamp((tension - 0.35) / 0.65, 0, 1) * 0.5
\t\ttunnel.HighGain = -18 * math.clamp((tension - 0.4) / 0.6, 0, 1)
\t\ttunnel.LowGain = 5 * math.clamp((tension - 0.4) / 0.6, 0, 1)
\tend

\tfor _, held in beds do
\t\theld.sound:Stop()
\t\theld.sound:Destroy()
\tend
\tsfxBus:Destroy()
\tmusicBus:Destroy()
end)

task.delay(DURATION + 1, function()
\treleaseCamera()
\tcamera.CameraType = originalCameraType
end)

print(string.format("Linen: %q — %d acteurs, %.2fs a %g fps, %d cues, %d evenements, %d nappes.",
\tSCENE_NAME, #tracks, DURATION, FPS, #CUES, #DIRECTOR, #beds))
'''
