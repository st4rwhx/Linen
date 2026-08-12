--!strict
--[[
	Linen runtime: the four modules wired together on one character.

	Use it directly for the common case, or ignore it and drive the modules
	yourself — they do not depend on each other, only on RigLimits.

		local Linen = require(ReplicatedStorage.Linen)
		local body = Linen.attach(character)

		-- a shot to the shoulder: the upper body gives, the legs keep going
		body:hit(character.RightUpperArm, direction * 900, hitPosition, {
			"RightShoulder", "RightElbow", "Waist", "Neck",
		})

	The ordering below is the part that is not obvious. Every frame:

	  1. the Animator writes the pose;
	  2. Momentum leans the spine on top of it (PreRender);
	  3. FootPlanting solves the legs onto the ground (PreRender, after);
	  4. physics steps, and any active ragdoll drive runs (PreSimulation);
	  5. Balance reads where the body ended up (PostSimulation).

	Reversing 2 and 3 is the classic mistake: leaning after the feet are planted
	drags them off the ground again.
]]

local RunService = game:GetService("RunService")

local Balance = require(script.Balance)
local FootPlanting = require(script.FootPlanting)
local Momentum = require(script.Momentum)
local Ragdoll = require(script.Ragdoll)
local RigLimits = require(script.RigLimits)

local Linen = {}
Linen.Balance = Balance
Linen.FootPlanting = FootPlanting
Linen.Momentum = Momentum
Linen.Ragdoll = Ragdoll
Linen.RigLimits = RigLimits

local Body = {}
Body.__index = Body

export type Body = typeof(setmetatable(
	{} :: {
		character: Model,
		rigName: string,
		ragdoll: Ragdoll.Ragdoll?,
		feet: FootPlanting.FootPlanting?,
		momentum: Momentum.Momentum?,
		balance: Balance.Balance?,
		_recovering: boolean,
	},
	Body
))

export type Options = {
	footPlanting: boolean?,
	momentum: boolean?,
	balance: boolean?,
	--[[ How hard a fallen body keeps trying. Zero is a corpse; around 0.3 is
	     someone who has been knocked down and is still tensed. ]]
	fallStrength: number?,
}

--[[ Foot planting and momentum are visual corrections, so they belong on the
     client that renders the character. Ragdoll and balance touch physics, so
     they belong wherever that character's parts are simulated. Attaching
     everything on both sides is the usual way this ends up jittering. ]]
function Linen.attach(character: Model, options: Options?): Body?
	local rigName = RigLimits.detect(character)
	if rigName == nil then
		warn(`Linen: {character.Name} is neither an R15 nor an R6 rig`)
		return nil
	end

	local opts = options or {}
	local client = RunService:IsClient()

	local self = setmetatable({
		character = character,
		rigName = rigName,
		ragdoll = Ragdoll.new(character),
		feet = nil,
		momentum = nil,
		balance = nil,
		_recovering = false,
	}, Body)

	if client and opts.footPlanting ~= false then
		self.feet = FootPlanting.new(character)
		if self.feet then
			self.feet:start()
		end
	end
	if client and opts.momentum ~= false then
		self.momentum = Momentum.new(character, rigName)
		if self.momentum then
			self.momentum:start()
		end
	end
	if opts.balance ~= false then
		self.balance = Balance.new(character)
		if self.balance then
			self.balance:start()
			self.balance:onFall(function(state)
				self:collapse(opts.fallStrength or state.support)
			end)
		end
	end

	return self
end

--[[ A hit. Naming joints ragdolls only those, which is how a shoulder wound
     reads as a stagger rather than a collapse: the legs are never told. ]]
function Body.hit(
	self: Body,
	part: BasePart,
	impulse: Vector3,
	worldPosition: Vector3?,
	joints: { string }?,
	strength: number?
)
	local ragdoll = self.ragdoll
	if ragdoll == nil then
		return
	end
	ragdoll:activate(strength or 0.55, joints)
	ragdoll:impulse(part, impulse, worldPosition)

	-- Ankles being pulled at by IK while the body is being thrown looks like
	-- the character is nailed to the floor.
	if joints == nil and self.feet then
		self.feet:setWeight(0)
	end
end

--[[ Balance lost. The drive is kept low but non-zero so the body breaks its
     own fall rather than arriving as dead weight — the difference between a
     ragdoll and a person going down. ]]
function Body.collapse(self: Body, strength: number)
	if self.ragdoll then
		self.ragdoll:activate(math.clamp(strength, 0, 0.5))
	end
	if self.feet then
		self.feet:setWeight(0)
	end
	if self.momentum then
		self.momentum:setWeight(0)
	end
end

--[[ Back to animation. Play a get-up animation over this; on its own it is a
     snap, because the Animator's pose and the ragdoll's are unrelated. ]]
function Body.recover(self: Body)
	if self.ragdoll then
		self.ragdoll:deactivate()
	end
	if self.feet then
		self.feet:setWeight(1)
	end
	if self.momentum then
		self.momentum:setWeight(1)
	end
	if self.balance then
		self.balance:onFall(function(state)
			self:collapse(state.support)
		end)
	end
end

function Body.destroy(self: Body)
	if self.ragdoll then
		self.ragdoll:destroy()
	end
	if self.feet then
		self.feet:destroy()
	end
	if self.momentum then
		self.momentum:stop()
	end
	if self.balance then
		self.balance:stop()
	end
end

Linen.Body = Body

return Linen
